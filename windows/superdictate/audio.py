"""Microphone capture.

macOS uses ``AVAudioEngine`` with a tap on the input node; the Windows port
uses PortAudio through ``sounddevice``, preferring the WASAPI host API so
device names match what the user sees in Windows settings and so shared
mode gives us the low latency the HUD's level meter needs.

Constants are carried over from ``main.swift`` unchanged: 16 kHz mono
float32, a 20-minute auto-stop, and a 0.25 s minimum clip below which a
recording is discarded as an accidental tap.
"""

from __future__ import annotations

import collections
import struct
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from . import paths
from .logging_setup import get as get_logger

log = get_logger("audio")

SAMPLE_RATE = 16_000
MAX_RECORDING_SECONDS = 20 * 60
MIN_CLIP_SECONDS = 0.25
BLOCK_FRAMES = 512  # 32 ms, smooth enough for the waveform, cheap enough to log
PREROLL_SECONDS = 0.4  # what a warm stream remembers from before the key press
PREROLL_BLOCKS = max(1, round(PREROLL_SECONDS * SAMPLE_RATE / BLOCK_FRAMES))
# A real stream open faster than this lets the start cue play before the
# stream is open; slower and the cue waits until capture is running.
STOP_CUE_GUARD_SECONDS = 0.5  # pre-roll ignores the previous clip's tail and stop cue
OPEN_FAST_MS = 60.0
OPEN_EMA_ALPHA = 0.3

PENDING_MAGIC = b"SDPD"
PENDING_VERSION = 1
PENDING_HEADER_SIZE = 16
PENDING_MAX_SECONDS = 30 * 60

# Stop-on-silence. The threshold is RMS amplitude, chosen well above room
# tone but below quiet speech; the delay is what the user asked for.
DEFAULT_SILENCE_STOP_SECONDS = 2.5
SILENCE_RMS_THRESHOLD = 0.012
SPEECH_RMS_THRESHOLD = 0.03


@dataclass(frozen=True)
class InputDevice:
    index: int
    name: str
    is_default: bool

    @property
    def key(self) -> str:
        """Stable identifier for settings: PortAudio indices shuffle when
        devices are plugged in, so the name is what gets persisted."""
        return self.name


def list_input_devices() -> list[InputDevice]:
    import sounddevice as sd

    try:
        devices = sd.query_devices()
        default_index = sd.default.device[0]
    except Exception as exc:  # no audio subsystem, no devices
        log.warning("Could not enumerate input devices: %s", exc)
        return []

    preferred_hostapi = _wasapi_index()
    result: list[InputDevice] = []
    seen: set[str] = set()
    for index, device in enumerate(devices):
        if device.get("max_input_channels", 0) < 1:
            continue
        if preferred_hostapi is not None and device.get("hostapi") != preferred_hostapi:
            continue
        name = str(device.get("name", "")).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(InputDevice(index, name, index == default_index))
    return result


def _wasapi_index() -> Optional[int]:
    import sounddevice as sd

    try:
        for index, api in enumerate(sd.query_hostapis()):
            if "WASAPI" in str(api.get("name", "")).upper():
                return index
    except Exception:
        pass
    return None


def resolve_device(name: str) -> Optional[int]:
    """Map a persisted device name back to a PortAudio index."""
    if not name:
        return None
    for device in list_input_devices():
        if device.name == name:
            return device.index
    log.warning("Configured input device %r is gone; falling back to default", name)
    return None


def device_sample_rate(device_index: Optional[int]) -> int:
    """The rate a device will actually open at.

    WASAPI in shared mode only accepts the endpoint's own mix rate, asking
    a 48 kHz microphone for 16 kHz fails outright with "Invalid sample
    rate", which is why every explicitly-chosen device used to be rejected
    while the system default (routed through MME, which resamples for us)
    worked. So we take whatever the device offers and resample ourselves.
    """
    import sounddevice as sd

    try:
        info = sd.query_devices(device_index if device_index is not None else None,
                                "input")
        rate = int(round(float(info["default_samplerate"])))
        return rate if rate > 0 else SAMPLE_RATE
    except Exception as exc:
        log.warning("Could not read the device's sample rate (%s); assuming %d Hz",
                    exc, SAMPLE_RATE)
        return SAMPLE_RATE


def _antialias_filter(source_rate: int, taps: int = 101) -> np.ndarray:
    """Windowed-sinc low-pass just under the 16 kHz Nyquist frequency.

    Decimating without this folds everything above 8 kHz back into the
    speech band as aliasing, which the model hears as noise.
    """
    cutoff = 0.9 * (SAMPLE_RATE / 2) / source_rate  # cycles per source sample
    n = np.arange(taps) - (taps - 1) / 2
    kernel = 2 * cutoff * np.sinc(2 * cutoff * n)
    kernel *= np.hamming(taps)
    return (kernel / np.sum(kernel)).astype(np.float32)


def resample_to_16k(samples: np.ndarray, source_rate: int) -> np.ndarray:
    """Convert captured audio to the 16 kHz mono the model expects."""
    if samples.size == 0 or source_rate == SAMPLE_RATE:
        return samples.astype(np.float32, copy=False)

    working = samples.astype(np.float32, copy=False)
    if source_rate > SAMPLE_RATE:
        working = np.convolve(working, _antialias_filter(source_rate), mode="same")

    duration = working.size / source_rate
    out_count = int(round(duration * SAMPLE_RATE))
    if out_count <= 0:
        return np.zeros(0, dtype=np.float32)
    # Linear interpolation is adequate once the signal is band-limited.
    source_positions = np.arange(working.size, dtype=np.float64)
    target_positions = np.arange(out_count, dtype=np.float64) * (source_rate / SAMPLE_RATE)
    return np.interp(target_positions, source_positions, working).astype(np.float32)


class Recorder:
    """One recording session at a time, owned by the app state machine."""

    def __init__(
        self,
        on_level: Optional[Callable[[float], None]] = None,
        on_auto_stop: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_level = on_level
        self._on_auto_stop = on_auto_stop
        self._stream = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._started_at = 0.0
        self._recording = False
        # False from halt() on: the clip ends there, whatever the stream
        # still delivers while it is being closed (the stop cue, say).
        self._accepting = False
        self._pending_handle = None
        # Rate that opened last time, per device name: skips the 16 kHz
        # attempt that WASAPI shared mode rejects for most endpoints.
        self._rate_cache: dict[str, int] = {}
        # Seconds a warm stream may idle before it is released, per mode.
        # ``always`` never is. Public so tests can shorten it.
        self.warm_idle_seconds: dict[str, Optional[float]] = {"1min": 60.0, "always": None}
        self._halted_at = 0.0
        self._warm_mode = "off"
        self._warm_device = ""
        self._stream_device = ""
        self._stream_lock = threading.RLock()
        self._idle_timer: Optional[threading.Timer] = None
        # Ring of the most recent blocks while no clip is being recorded.
        self._preroll: collections.deque = collections.deque(
            maxlen=PREROLL_BLOCKS)
        # EMA of how long a real stream open took (ms); 0 = never measured.
        self.open_ms_ema = 0.0
        self.on_open_measured: Optional[Callable[[float], None]] = None
        self._auto_stop_fired = False
        self._capture_rate = SAMPLE_RATE
        self.last_error: Optional[str] = None
        # perf_counter_ns marks of the last start()/stop(), for the
        # --bench-record-latency diagnostic. Four dict writes: free.
        self.trace: dict[str, int] = {}

        # Stop-on-silence. Counting only starts once the speaker has
        # actually said something, so a pause before the first word never
        # ends the recording.
        self.silence_stop_enabled = False
        self.silence_stop_seconds = DEFAULT_SILENCE_STOP_SECONDS
        self._heard_speech = False
        self._silence_started_at = 0.0

    @property
    def capture_rate(self) -> int:
        return self._capture_rate

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._started_at if self._recording else 0.0

    # -- opening -----------------------------------------------------

    def cue_before_open(self, device_name: str = "") -> bool:
        """May the start cue play before the microphone is open?

        Only when the capture will start about as fast as the cue: the
        stream is already open, or the last real open was quick. A device
        that takes a few hundred milliseconds (Bluetooth, USB) would
        otherwise let the cue sound while nothing is listening yet, and
        the first words would be lost. An install that has never opened a
        stream has no measurement and takes the careful order.
        """
        if self._warm_ready(device_name):
            return True
        return 0.0 < self.open_ms_ema < OPEN_FAST_MS

    def _note_open_time(self, milliseconds: float) -> None:
        previous = self.open_ms_ema
        self.open_ms_ema = (milliseconds if previous <= 0.0
                            else previous + OPEN_EMA_ALPHA * (milliseconds - previous))
        if self.on_open_measured is not None:
            try:
                self.on_open_measured(self.open_ms_ema)
            except Exception:
                pass

    def _open_stream(self, device_name: str) -> bool:
        """Open and start the input stream. Caller holds ``_stream_lock``."""
        import sounddevice as sd

        device_index = resolve_device(device_name)

        # 16 kHz first (no resampling to pay for), then the device's own
        # rate, which is the only one WASAPI shared mode will grant.
        self.trace["device_resolved"] = time.perf_counter_ns()
        native_rate = device_sample_rate(device_index)
        self.trace["rate_known"] = time.perf_counter_ns()
        candidates = [SAMPLE_RATE] if native_rate == SAMPLE_RATE else [SAMPLE_RATE, native_rate]
        cached = self._rate_cache.get(device_name)
        if cached in candidates:
            candidates.remove(cached)
            candidates.insert(0, cached)

        last_error: Optional[Exception] = None
        for rate in candidates:
            try:
                stream = sd.InputStream(
                    samplerate=rate,
                    channels=1,
                    dtype="float32",
                    blocksize=max(256, int(BLOCK_FRAMES * rate / SAMPLE_RATE)),
                    device=device_index,
                    callback=self._callback,
                )
                self.trace["stream_created"] = time.perf_counter_ns()
                stream.start()
                self.trace["stream_started"] = time.perf_counter_ns()
            except Exception as exc:
                last_error = exc
                log.debug("Device rejected %d Hz: %s", rate, exc)
                continue
            self._stream = stream
            self._stream_device = device_name
            self._capture_rate = rate
            self._rate_cache[device_name] = rate
            self._note_open_time(
                (self.trace["stream_started"] - self.trace["rate_known"]) / 1e6)
            return True

        self.last_error = str(last_error)
        log.error("Could not open input stream: %s", last_error)
        self._stream = None
        return False

    def _close_stream(self) -> None:
        """Caller holds ``_stream_lock``."""
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as exc:
                log.warning("Error closing input stream: %s", exc)
        with self._lock:  # after the last callback has run
            self._preroll.clear()

    def start(self, device_name: str = "") -> bool:
        if self._recording:
            return True
        self.trace = {"start_call": time.perf_counter_ns()}
        self.last_error = None
        self._auto_stop_fired = False
        self._heard_speech = False
        self._silence_started_at = 0.0

        with self._stream_lock:
            self._cancel_idle_timer()
            if self._warm_ready(device_name):
                # The stream is already running: take what it heard in the
                # last fraction of a second too, so a word begun just
                # before the key went down is not clipped.
                with self._lock:
                    # Not the tail of the last clip or its stop cue.
                    cutoff = self._halted_at + STOP_CUE_GUARD_SECONDS
                    self._chunks = [block for heard, block in self._preroll
                                    if heard >= cutoff]
                    self._preroll.clear()
                    self._open_pending_file()
                    for chunk in self._chunks:
                        self._append_pending(chunk)
                    self._accepting = True
                if self._chunks:
                    self.trace["first_block"] = time.perf_counter_ns()
                self.trace["warm"] = 1
            else:
                self._close_stream()  # a dead or other-device stream
                with self._lock:
                    self._chunks = []
                # Before the stream exists, so not one block of it can be dropped.
                self._accepting = True
                if not self._open_stream(device_name):
                    self._accepting = False
                    return False
                self._open_pending_file()
            self._started_at = time.monotonic()
            self._recording = True
        self.trace["start_return"] = time.perf_counter_ns()
        log.info("Recording started (device=%s, %d Hz%s%s)",
                 device_name or "system default", self._capture_rate,
                 "" if self._capture_rate == SAMPLE_RATE else ", resampling to 16 kHz",
                 ", warm stream" if self.trace.get("warm") else "")
        return True

    def halt(self) -> None:
        """End the clip *now*, without waiting for the stream to close.

        Closing a WASAPI stream and resampling a long clip take tens to
        hundreds of milliseconds; the stop cue must not wait for them, and
        must not end up in the clip either. Call stop() afterwards to
        collect the audio.
        """
        self._halted_at = time.monotonic()
        self._accepting = False

    def stop(self) -> np.ndarray:
        if not self._recording:
            return np.zeros(0, dtype=np.float32)
        self._recording = False
        if self._accepting:
            self.halt()
        self.trace["stop_call"] = time.perf_counter_ns()
        with self._stream_lock:
            if self._warm_mode != "off":
                self._schedule_idle_close()  # stays open for the next press
            else:
                self._close_stream()
        self.trace["stream_closed"] = time.perf_counter_ns()

        self._close_pending_file()
        with self._lock:
            chunks = self._chunks
            self._chunks = []
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        captured = np.concatenate(chunks).astype(np.float32, copy=False)
        out = resample_to_16k(captured, self._capture_rate)
        self.trace["stop_return"] = time.perf_counter_ns()
        return out

    # -- instant start (opt-in warm stream) -------------------------------
    #
    # With the setting on, the input stream is kept open between
    # dictations. While no recording runs, the callback keeps only the last
    # PREROLL_SECONDS in a ring buffer in memory: nothing is written to
    # disk, nothing is sent anywhere, and the oldest block is overwritten
    # as the newest arrives. A key press then just starts keeping blocks
    # (the ring first) instead of opening a device.

    def _warm_ready(self, device_name: str) -> bool:
        stream = self._stream
        return (stream is not None and self._stream_device == device_name
                and bool(getattr(stream, "active", True)))

    def configure_warm(self, mode: str, device_name: str = "") -> None:
        """Apply the instant-start setting: ``off`` | ``1min`` | ``always``."""
        if mode not in ("off", "1min", "always"):
            mode = "off"
        self._warm_mode = mode
        self._warm_device = device_name
        if self._recording:
            return  # applied when the clip ends
        if mode == "always":
            threading.Thread(target=self._warm_up, name="mic-warm-up",
                             daemon=True).start()
        else:
            with self._stream_lock:
                self._cancel_idle_timer()
                if mode == "off" or self._stream_device != device_name:
                    self._close_stream()
                else:
                    self._schedule_idle_close()

    def _warm_up(self) -> None:
        with self._stream_lock:
            if self._recording or self._warm_mode != "always":
                return
            if self._warm_ready(self._warm_device):
                return
            self._close_stream()
            self._accepting = False
            self.trace = {"start_call": time.perf_counter_ns()}
            self._open_stream(self._warm_device)

    def _schedule_idle_close(self) -> None:
        """Caller holds ``_stream_lock``."""
        self._cancel_idle_timer()
        seconds = self.warm_idle_seconds.get(self._warm_mode)
        if seconds is None or self._stream is None:
            return
        timer = threading.Timer(seconds, self._idle_close)
        timer.daemon = True
        self._idle_timer = timer
        timer.start()

    def _cancel_idle_timer(self) -> None:
        timer, self._idle_timer = self._idle_timer, None
        if timer is not None:
            timer.cancel()

    def _idle_close(self) -> None:
        with self._stream_lock:
            if self._recording:
                return
            log.info("Microphone released after being idle")
            self._close_stream()

    def shutdown(self) -> None:
        self._warm_mode = "off"
        with self._stream_lock:
            self._cancel_idle_timer()
            if not self._recording:
                self._close_stream()

    def snapshot(self, max_seconds: float = 0.0) -> np.ndarray:
        """Everything captured so far, leaving the recording running.

        ``max_seconds`` trims to the most recent stretch before resampling
        rather than after, because the anti-alias convolution is the
        expensive part and this runs on a timer while the microphone is
        still open.
        """
        with self._lock:
            chunks = list(self._chunks)
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        captured = np.concatenate(chunks).astype(np.float32, copy=False)
        if max_seconds > 0:
            limit = int(max_seconds * self._capture_rate)
            if captured.size > limit:
                captured = captured[-limit:]
        return resample_to_16k(captured, self._capture_rate)

    def discard(self) -> None:
        self.stop()
        clear_pending_dictation()

    # -- stream callback ---------------------------------------------

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            log.debug("Input stream status: %s", status)
        samples = indata[:, 0].copy()
        with self._lock:
            if not self._accepting:
                # Not recording: only the short ring buffer is kept.
                self._preroll.append((time.monotonic(), samples))
                return
            if "first_block" not in self.trace:
                self.trace["first_block"] = time.perf_counter_ns()
            self._chunks.append(samples)
        self._append_pending(samples)

        rms = float(np.sqrt(np.mean(np.square(samples)))) if frames else 0.0
        if self._on_level is not None:
            # A light expansion so quiet speech still animates the meter.
            try:
                self._on_level(min(1.0, rms * 6.0))
            except Exception:
                pass

        if (
            not self._auto_stop_fired
            and (self.elapsed >= MAX_RECORDING_SECONDS or self._silence_elapsed(rms))
            and self._on_auto_stop is not None
        ):
            self._auto_stop_fired = True
            try:
                self._on_auto_stop()
            except Exception:
                pass

    def _silence_elapsed(self, rms: float) -> bool:
        """True once the speaker has gone quiet for long enough to stop.

        Two thresholds with a gap between them, so a voice hovering right
        at the cutoff does not flicker the timer on and off.
        """
        if not self.silence_stop_enabled:
            return False

        now = time.monotonic()
        if rms >= SPEECH_RMS_THRESHOLD:
            self._heard_speech = True
            self._silence_started_at = 0.0
            return False
        if not self._heard_speech:
            # Nothing said yet, the user is still gathering their thoughts.
            return False
        if rms >= SILENCE_RMS_THRESHOLD:
            return False

        if self._silence_started_at == 0.0:
            self._silence_started_at = now
            return False
        return (now - self._silence_started_at) >= self.silence_stop_seconds

    # -- crash recovery ----------------------------------------------
    #
    # Audio is streamed to disk as it arrives so a power loss or a crash
    # mid-dictation leaves a recoverable clip, exactly like the macOS
    # pending-dictation file. Header: magic, version, sample rate, and a
    # reserved word to keep it 16 bytes.

    def _open_pending_file(self) -> None:
        try:
            paths.ensure_directories()
            handle = open(paths.PENDING_DICTATION_FILE, "wb")
            handle.write(
                struct.pack("<4sIII", PENDING_MAGIC, PENDING_VERSION,
                            self._capture_rate, 0)
            )
            handle.flush()
            self._pending_handle = handle
        except OSError as exc:
            log.warning("Could not open pending dictation file: %s", exc)
            self._pending_handle = None

    def _append_pending(self, samples: np.ndarray) -> None:
        handle = self._pending_handle
        if handle is None:
            return
        try:
            if handle.tell() >= PENDING_HEADER_SIZE + PENDING_MAX_SECONDS * SAMPLE_RATE * 4:
                return
            handle.write(samples.tobytes())
        except (OSError, ValueError):
            self._pending_handle = None

    def _close_pending_file(self) -> None:
        handle = self._pending_handle
        self._pending_handle = None
        if handle is None:
            return
        try:
            handle.flush()
            handle.close()
        except OSError:
            pass


def read_pending_dictation() -> Optional[np.ndarray]:
    """Recover audio left behind by a crash, if it is long enough to matter."""
    try:
        with open(paths.PENDING_DICTATION_FILE, "rb") as handle:
            header = handle.read(PENDING_HEADER_SIZE)
            if len(header) < PENDING_HEADER_SIZE:
                return None
            magic, version, rate, _ = struct.unpack("<4sIII", header)
            if magic != PENDING_MAGIC or version != PENDING_VERSION or rate <= 0:
                return None
            payload = handle.read(PENDING_MAX_SECONDS * rate * 4)
    except OSError:
        return None

    usable = len(payload) - (len(payload) % 4)
    if usable <= 0:
        return None
    samples = np.frombuffer(payload[:usable], dtype=np.float32)
    if samples.size < MIN_CLIP_SECONDS * rate:
        return None
    # The clip was written at whatever rate the device ran at.
    return resample_to_16k(samples.copy(), rate)


def clear_pending_dictation() -> None:
    try:
        paths.PENDING_DICTATION_FILE.unlink()
    except OSError:
        pass
