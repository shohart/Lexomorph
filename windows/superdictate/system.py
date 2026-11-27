"""Small Windows integrations: output muting, feedback sounds, autostart
and single-instance enforcement.

Each of these replaces a macOS-specific mechanism:

===========================  ==========================================
macOS                        Windows
===========================  ==========================================
CoreAudio default device     ``IAudioEndpointVolume`` via pycaw
``NSSound`` system sounds    generated tones via ``winsound``
``~/Library/LaunchAgents``   ``HKCU\\...\\CurrentVersion\\Run``
PID file in Application      a named kernel mutex
Support
===========================  ==========================================
"""

from __future__ import annotations

import atexit
import ctypes
import ctypes.wintypes as wt
import io
import math
import os
import queue
import struct
import sys
import threading
import time
import wave
from functools import lru_cache
from typing import Callable, Optional

from . import paths
from .logging_setup import get as get_logger

log = get_logger("system")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


# -- system output mute --------------------------------------------------


def _speaker_interface(interface_type):
    """Activate a COM interface on the default playback device.

    ``AudioUtilities.GetSpeakers()`` used to hand back the raw IMMDevice;
    since pycaw 2024 it hands back an ``AudioDevice`` wrapper, which has no
    ``Activate``. Calling it regardless is how muting quietly stopped
    working: the AttributeError was caught, logged and swallowed.

    The result is obtained through ``QueryInterface`` rather than
    ``ctypes.cast``. Casting builds a second Python object over the same
    COM pointer without adding a reference to it, so the two objects
    together release one reference twice; the object is freed while the
    app still holds a pointer to it, and the next garbage collection to
    touch that pointer takes the whole process down with an access
    violation, far from anything to do with audio.
    """
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities

    device = AudioUtilities.GetSpeakers()
    device = getattr(device, "_dev", device)
    unknown = device.Activate(interface_type._iid_, CLSCTX_ALL, None)
    return unknown.QueryInterface(interface_type)


class OutputMute:
    """Mutes the default playback device for the duration of a recording.

    macOS mutes so the microphone does not pick up whatever is playing.
    The same reasoning applies here, but the device mute flag outlives the
    process that set it: whatever kills the app mid-recording — a crash, a
    killed task, a power loss — leaves the machine silent, with nothing on
    screen to connect the silence to this app.

    So the mute is guarded twice. ``atexit`` covers an orderly exit and an
    unhandled exception, and a marker file on disk covers everything else:
    it is written before the device is touched and removed after it is put
    back, so the next launch can see that the last one muted and never
    unmuted, and undo it.
    """

    def __init__(self) -> None:
        self._previous: Optional[bool] = None
        self._lock = threading.Lock()
        atexit.register(self.restore)

    def _endpoint(self):
        from pycaw.pycaw import IAudioEndpointVolume

        return _speaker_interface(IAudioEndpointVolume)

    def mute(self) -> None:
        with self._lock:
            if self._previous is not None:
                return
            try:
                import comtypes

                comtypes.CoInitialize()
                volume = self._endpoint()
                self._previous = bool(volume.GetMute())
                if not self._previous:
                    # Written first: a marker that arrives after the mute
                    # would be missing in exactly the case it exists for.
                    _write_mute_marker()
                    volume.SetMute(1, None)
            except Exception as exc:
                log.warning("Could not mute system output: %s", exc)
                self._previous = None

    def restore(self) -> None:
        with self._lock:
            if self._previous is None:
                return
            was_muted = self._previous
            self._previous = None
            if was_muted:
                return
            try:
                import comtypes

                comtypes.CoInitialize()
                self._endpoint().SetMute(0, None)
                _clear_mute_marker()
            except Exception as exc:
                log.warning("Could not restore system output: %s", exc)

    @staticmethod
    def recover() -> bool:
        """Undo a mute left behind by a previous run. Returns True if it did.

        Called at startup. The marker means the last run muted the device
        and never got as far as putting it back, so the user has been
        looking at a silent machine with no idea why.
        """
        if not paths.MUTE_MARKER_FILE.exists():
            return False
        try:
            import comtypes

            comtypes.CoInitialize()
            _speaker_interface(_endpoint_volume_type()).SetMute(0, None)
            log.info("Restored system output muted by a previous run")
        except Exception as exc:
            log.warning("Could not restore output after a previous run: %s", exc)
            return False
        finally:
            _clear_mute_marker()
        return True


def _endpoint_volume_type():
    from pycaw.pycaw import IAudioEndpointVolume

    return IAudioEndpointVolume


def _write_mute_marker() -> None:
    try:
        paths.MUTE_MARKER_FILE.write_text("muted", encoding="utf-8")
    except OSError as exc:
        log.warning("Could not write the mute marker: %s", exc)


def _clear_mute_marker() -> None:
    try:
        paths.MUTE_MARKER_FILE.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("Could not clear the mute marker: %s", exc)


# -- media pause ---------------------------------------------------------


VK_MEDIA_PLAY_PAUSE = 0xB3
KEYEVENTF_KEYUP = 0x0002
# Anything quieter than this is background hiss from a session that is open
# but not playing; anything louder is something the user is listening to.
_AUDIBLE_PEAK = 0.004
# One reading can land in a gap between words or beats, so two quick readings
# are taken (10 ms apart). Runs asynchronously in parallel with microphone open
# so it never delays recording start.
_PEAK_SAMPLES = 2
_PEAK_INTERVAL = 0.010


class MediaPause:
    """Presses the play/pause media key around a recording.

    Muting silences the speakers but the video keeps running, so the
    dictation costs you the part you were watching. The media key is what a
    keyboard would send, so whatever owns playback — a player, a browser
    tab — handles it the way it handles the real thing.

    The key is a toggle, which makes an unconditional press dangerous: with
    nothing playing it would *start* something. So playback is confirmed
    first by metering the output device, and the key is only pressed again
    afterwards if this class was the one that paused it.
    """

    def __init__(self) -> None:
        self._paused = False
        self._lock = threading.Lock()

    @staticmethod
    def _something_is_playing() -> bool:
        from pycaw.api.endpointvolume import IAudioMeterInformation

        meter = _speaker_interface(IAudioMeterInformation)
        for index in range(_PEAK_SAMPLES):
            if float(meter.GetPeakValue()) > _AUDIBLE_PEAK:
                return True
            if index + 1 < _PEAK_SAMPLES:
                time.sleep(_PEAK_INTERVAL)
        return False

    @staticmethod
    def _tap() -> None:
        user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
        user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, KEYEVENTF_KEYUP, 0)

    def pause(self) -> None:
        """Pause playback if there is any.

        Runs before the output is muted and before the start cue: a muted
        device meters as silence, and our own cue would meter as music.
        """
        with self._lock:
            if self._paused:
                return
            try:
                import comtypes

                comtypes.CoInitialize()
                if not self._something_is_playing():
                    return
                self._tap()
                self._paused = True
            except Exception as exc:
                log.warning("Could not pause playback: %s", exc)
                self._paused = False

    def pause_async(self) -> threading.Event:
        """Run :meth:`pause` off the recording-start critical path.

        Returns an event that is set as soon as metering/pausing finishes so
        :class:`OutputMute` can wait for it without blocking microphone open.
        """
        done = threading.Event()

        def work() -> None:
            try:
                self.pause()
            finally:
                done.set()

        threading.Thread(target=work, name="media-pause", daemon=True).start()
        return done

    def resume(self) -> None:
        with self._lock:
            if not self._paused:
                return
            self._paused = False
            try:
                self._tap()
            except Exception as exc:
                log.warning("Could not resume playback: %s", exc)


# -- feedback sounds -----------------------------------------------------


CUE_SAMPLE_RATE = 44100


@lru_cache(maxsize=8)
def _cue(segments: tuple[tuple[int, int], ...], volume: float = 0.22) -> bytes:
    """Render a sequence of (frequency Hz, duration ms) tones to a WAV.

    A frequency of zero is silence. The phase carries across segments and
    the whole clip gets a short attack and release, because a sine that
    starts or stops at a non-zero value clicks, and a click is exactly the
    kind of cheap-sounding detail these cues exist to avoid.
    """
    total = sum(CUE_SAMPLE_RATE * ms // 1000 for _, ms in segments)
    attack = int(CUE_SAMPLE_RATE * 0.004)
    release = int(CUE_SAMPLE_RATE * 0.020)
    frames = bytearray()
    phase = 0.0
    index = 0

    for frequency, milliseconds in segments:
        count = CUE_SAMPLE_RATE * milliseconds // 1000
        step = 2.0 * math.pi * frequency / CUE_SAMPLE_RATE
        for _ in range(count):
            if index < attack:
                envelope = index / attack
            elif index > total - release:
                envelope = max(0.0, (total - index) / release)
            else:
                envelope = 1.0
            sample = math.sin(phase) if frequency else 0.0
            frames += struct.pack("<h", int(32767 * volume * envelope * sample))
            phase += step
            index += 1

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(CUE_SAMPLE_RATE)
        out.writeframes(bytes(frames))
    return buffer.getvalue()


@lru_cache(maxsize=4)
def _cue_file(event: str) -> bytes:
    """The bundled WAV for ``event``, read once; empty if it is missing."""
    path = paths.resource_path("assets", Sounds._FILES[event])
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _wav_to_pcm(data: bytes) -> tuple[object, int]:
    """Decode a 16-bit PCM WAV byte buffer into ``(float32[N, 2], samplerate)``."""
    import numpy as np

    with wave.open(io.BytesIO(data), "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        raw = w.readframes(w.getnframes())
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch == 1:
        pcm = np.column_stack((pcm, pcm))
    else:
        pcm = pcm.reshape(-1, ch)[:, :2]
    return np.ascontiguousarray(pcm, dtype=np.float32), sr


def _resample_stereo(pcm, src_sr: int, dst_sr: int):
    import numpy as np

    if src_sr == dst_sr or len(pcm) == 0:
        return pcm
    n_out = max(1, int(round(len(pcm) * dst_sr / src_sr)))
    x_old = np.linspace(0.0, 1.0, len(pcm), endpoint=False)
    x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
    left = np.interp(x_new, x_old, pcm[:, 0])
    right = np.interp(x_new, x_old, pcm[:, 1])
    return np.ascontiguousarray(np.column_stack((left, right)), dtype=np.float32)


def _wasapi_output_device() -> tuple[Optional[int], int]:
    """Return ``(device_index, default_samplerate)`` preferring WASAPI."""
    import sounddevice as sd

    try:
        for api in sd.query_hostapis():
            if "wasapi" in str(api.get("name", "")).lower():
                idx = api.get("default_output_device", -1)
                if isinstance(idx, int) and idx >= 0:
                    info = sd.query_devices(idx)
                    return idx, int(info.get("default_samplerate") or 48000)
    except Exception:
        pass
    try:
        idx = sd.default.device[1]
        if isinstance(idx, int) and idx >= 0:
            info = sd.query_devices(idx)
            return idx, int(info.get("default_samplerate") or 48000)
    except Exception:
        pass
    return None, 48000


_CUE_PACKS = ("focus", "select", "check", "redo", "open", "start")


class Sounds:
    """Zero-latency non-blocking cues for start / stop / error via WASAPI.

    Keeps a lightweight PortAudio/WASAPI ``OutputStream`` callback running
    while feedback sounds are enabled so playing a cue never pays device
    wake-up latency (1-2s on laptop audio codecs) and never clips the tail
    by closing the stream prematurely.
    """

    _FILES = {
        "start": "record-start.wav",
        "stop": "record-stop.wav",
    }
    _TONES: dict[str, tuple[tuple[int, int], ...]] = {
        "error": ((330, 90), (0, 45), (330, 110)),
        "rejected": ((420, 55),),
    }

    _DEFAULT_IDLE_SECONDS = 5.0
    _WARMUP_PAD_SECONDS = 0.085

    def __init__(self, enabled: bool = True,
                 enabled_getter: Optional[Callable[[], bool]] = None,
                 pack_getter: Optional[Callable[[], str]] = None,
                 idle_seconds_getter: Optional[Callable[[], Optional[float]]] = None) -> None:
        self._enabled = bool(enabled)
        self._enabled_getter = enabled_getter
        self._pack_getter = pack_getter
        self._idle_seconds_getter = idle_seconds_getter
        self._pcm_cache: dict[tuple[str, str], tuple[object, int]] = {}
        self._out_device: Optional[int] = None
        self._out_sr: int = 48000
        self._stream = None
        self._stream_started_at: float = 0.0
        self._stream_lock = threading.Lock()
        self._play_lock = threading.Lock()
        self._idle_timer: Optional[threading.Timer] = None
        self._active_pcm = None
        self._active_pos: int = 0
        self._active_then: Optional[Callable[[], None]] = None
        self._ready = False
        self._closed = False
        self._preload_thread = threading.Thread(
            target=self._init_audio, name="sound-init", daemon=True
        )
        self._preload_thread.start()
        import weakref
        ref = weakref.ref(self)
        atexit.register(lambda r=ref: (s := r()) and s.close())

    def close(self) -> None:
        self._closed = True
        self._cancel_idle_timer()
        with self._play_lock:
            self._active_pcm = None
            self._active_pos = 0
            self._active_then = None
        self._close_stream()

    def _cancel_idle_timer(self) -> None:
        timer, self._idle_timer = self._idle_timer, None
        if timer is not None:
            timer.cancel()

    def _idle_seconds(self) -> Optional[float]:
        if self._idle_seconds_getter is not None:
            return self._idle_seconds_getter()
        return self._DEFAULT_IDLE_SECONDS

    def refresh_idle_policy(self) -> None:
        """Apply updated instant-start idle policy to the sound stream."""
        if self._closed or not self._is_enabled():
            return
        if self._idle_seconds() is None:
            self.warm_async()
        elif self._stream is not None:
            self._schedule_idle_close()

    def _schedule_idle_close(self) -> None:
        self._cancel_idle_timer()
        if self._closed:
            return
        delay = self._idle_seconds()
        if delay is None:
            return
        interval = max(0.2, float(delay))
        timer = threading.Timer(interval, self._on_idle_timeout)
        timer.daemon = True
        timer.name = "sound-idle-close"
        self._idle_timer = timer
        timer.start()

    def _on_idle_timeout(self) -> None:
        with self._play_lock:
            if self._active_pcm is not None:
                self._schedule_idle_close()
                return
        self._close_stream()

    def warm_async(self) -> None:
        """Pre-warm the WASAPI output stream in the background (e.g. on key press)."""
        if self._closed or not self._is_enabled():
            return
        if self._stream is not None:
            self._schedule_idle_close()
            return
        threading.Thread(target=self._warm_sync, name="sound-warm", daemon=True).start()

    def _warm_sync(self) -> None:
        if not self._ready:
            self._preload_thread.join(timeout=2.0)
        if not self._closed and self._is_enabled():
            if self._ensure_stream():
                self._schedule_idle_close()

    @property
    def enabled(self) -> bool:
        if self._enabled_getter is not None:
            return bool(self._enabled_getter())
        return bool(self._enabled)

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = bool(value)
        if not self._enabled:
            with self._play_lock:
                self._active_pcm = None
                self._active_pos = 0
                then, self._active_then = self._active_then, None
            if then is not None:
                threading.Thread(target=then, name="after-cue", daemon=True).start()
            self._close_stream()
        else:
            threading.Thread(target=self._ensure_stream, name="sound-open", daemon=True).start()

    def _is_enabled(self) -> bool:
        return self.enabled

    def _current_pack(self) -> str:
        if self._pack_getter is not None:
            return str(self._pack_getter() or "default")
        return "default"

    def _init_audio(self) -> None:
        dev, sr = _wasapi_output_device()
        self._out_device = dev
        self._out_sr = sr
        for event in self._FILES:
            try:
                data = _cue_file(event)
                if data:
                    pcm, wav_sr = _wav_to_pcm(data)
                    self._pcm_cache[("default", event)] = (_resample_stereo(pcm, wav_sr, sr), sr)
            except Exception as exc:
                log.debug("Could not preload the %s cue: %s", event, exc)
        for pack in _CUE_PACKS:
            for event in ("start", "stop"):
                try:
                    path = paths.resource_path("assets", "cues", f"{pack}-{event}.wav")
                    if path.is_file():
                        pcm, wav_sr = _wav_to_pcm(path.read_bytes())
                        self._pcm_cache[(pack, event)] = (_resample_stereo(pcm, wav_sr, sr), sr)
                except Exception as exc:
                    log.debug("Could not preload %s/%s cue: %s", pack, event, exc)
        for event, segments in self._TONES.items():
            try:
                pcm, wav_sr = _wav_to_pcm(_cue(segments))
                self._pcm_cache[("default", event)] = (_resample_stereo(pcm, wav_sr, sr), sr)
            except Exception as exc:
                log.debug("Could not preload the %s tone: %s", event, exc)
        self._ready = True

    def _audio_callback(self, outdata, frames: int, _time, _status) -> None:
        then_to_call: Optional[Callable[[], None]] = None
        with self._play_lock:
            pcm = self._active_pcm
            if pcm is None:
                outdata.fill(0.0)
                return
            pos = self._active_pos
            rem = len(pcm) - pos
            if rem <= 0:
                outdata.fill(0.0)
                self._active_pcm = None
                self._active_pos = 0
                then_to_call, self._active_then = self._active_then, None
            elif rem >= frames:
                outdata[:] = pcm[pos:pos + frames]
                self._active_pos = pos + frames
                if self._active_pos >= len(pcm):
                    self._active_pcm = None
                    self._active_pos = 0
                    then_to_call, self._active_then = self._active_then, None
            else:
                outdata[:rem] = pcm[pos:]
                outdata[rem:].fill(0.0)
                self._active_pcm = None
                self._active_pos = 0
                then_to_call, self._active_then = self._active_then, None
        if then_to_call is not None:
            threading.Thread(target=then_to_call, name="after-cue", daemon=True).start()

    def _ensure_stream(self) -> bool:
        import sounddevice as sd

        if self._closed or not self._ready:
            return False
        with self._stream_lock:
            if self._closed:
                return False
            if self._stream is not None:
                try:
                    if self._stream.active:
                        return True
                except Exception:
                    pass
                self._close_stream_locked()
            try:
                stream = sd.OutputStream(
                    device=self._out_device,
                    samplerate=self._out_sr,
                    channels=2,
                    dtype="float32",
                    blocksize=512,
                    latency="low",
                    callback=self._audio_callback,
                )
                stream.start()
                self._stream = stream
                self._stream_started_at = time.monotonic()
                return True
            except Exception as exc:
                log.debug("Could not open persistent WASAPI output stream: %s", exc)
                self._stream = None
                return False

    def _close_stream_locked(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def _close_stream(self) -> None:
        with self._stream_lock:
            self._close_stream_locked()

    def _play_winsound_fallback(self, event: str, blocking: bool) -> None:
        import winsound

        if event in self._FILES:
            path = str(paths.resource_path("assets", self._FILES[event]))
            if os.path.exists(path):
                flags = winsound.SND_FILENAME | winsound.SND_NODEFAULT
                if not blocking:
                    flags |= winsound.SND_ASYNC
                winsound.PlaySound(path, flags)
                return
        segments = self._TONES.get(event)
        if segments is not None:
            winsound.PlaySound(_cue(segments), winsound.SND_MEMORY | winsound.SND_NODEFAULT)

    def _schedule_pcm(self, pcm, then: Optional[Callable[[], None]]) -> None:
        if not self._ensure_stream():
            # Fallback if audio output stream could not be opened.
            if then is not None:
                threading.Thread(target=then, name="after-cue", daemon=True).start()
            return
        # Wait-free hardware unmute pad: a freshly started WASAPI OutputStream
        # takes ~60-85 ms for the DAC/amp to unmute, so prepend silent frames
        # instead of losing the attack of short cues.
        elapsed = time.monotonic() - self._stream_started_at
        if 0.0 <= elapsed < self._WARMUP_PAD_SECONDS:
            import numpy as np

            pad_frames = int(self._out_sr * (self._WARMUP_PAD_SECONDS - elapsed))
            if pad_frames > 0:
                pcm = np.ascontiguousarray(
                    np.vstack((np.zeros((pad_frames, 2), dtype=np.float32), pcm)),
                    dtype=np.float32,
                )
        old_then: Optional[Callable[[], None]] = None
        with self._play_lock:
            old_then = self._active_then
            self._active_pcm = pcm
            self._active_pos = 0
            self._active_then = then
        self._schedule_idle_close()
        if old_then is not None:
            threading.Thread(target=old_then, name="after-cue", daemon=True).start()

    def play(self, event: str, then: Optional[Callable[[], None]] = None) -> None:
        """Play a cue, and run ``then`` once it has finished sounding."""
        if not self._is_enabled():
            if then is not None:
                threading.Thread(target=then, name="after-cue", daemon=True).start()
            return
        pack = self._current_pack()
        cached = self._pcm_cache.get((pack, event)) or self._pcm_cache.get(("default", event))
        if cached is not None and self._ready and self._stream is not None:
            self._schedule_pcm(cached[0], then)
            return

        def _deferred() -> None:
            if not self._ready:
                self._preload_thread.join(timeout=2.0)
            c = self._pcm_cache.get((pack, event)) or self._pcm_cache.get(("default", event))
            if c is not None and self._ensure_stream():
                self._schedule_pcm(c[0], then)
            else:
                try:
                    self._play_winsound_fallback(event, blocking=(then is not None))
                except Exception as exc:
                    log.debug("Fallback cue %s/%s failed: %s", pack, event, exc)
                if then is not None:
                    then()

        threading.Thread(target=_deferred, name="sound-play", daemon=True).start()

    def preview_pack(self, pack: str) -> None:
        """Play the full start + pause + stop pair from ``pack`` without clipping."""
        def _run() -> None:
            import numpy as np

            if not self._ready:
                self._preload_thread.join(timeout=2.0)
            s_entry = self._pcm_cache.get((pack, "start")) or self._pcm_cache.get(("default", "start"))
            e_entry = self._pcm_cache.get((pack, "stop")) or self._pcm_cache.get(("default", "stop"))
            if s_entry is None or e_entry is None:
                return
            sr = s_entry[1]
            gap = np.zeros((max(1, int(sr * 0.18)), 2), dtype=np.float32)
            combined = np.ascontiguousarray(np.vstack((s_entry[0], gap, e_entry[0])), dtype=np.float32)
            self._schedule_pcm(combined, None)

        threading.Thread(target=_run, name="sound-preview", daemon=True).start()


# -- autostart -----------------------------------------------------------

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "Lexomorph"
# The app was called D1CT, then Dictation, then SuperDictate (until 1.0.0).
# Its autostart entry names an executable that is no longer installed, so
# it is cleared whenever this one is written or removed; left alone it
# would fail silently at every login.
_LEGACY_RUN_VALUES = ("D1CT", "SuperDictate")


def _launch_command() -> str:
    """The command Windows runs at login, tray-only.

    ``--minimized`` is the whole point of the entry: a copy started by
    the system should appear in the tray and wait for the hotkey, not
    throw a window over whatever the user is logging in to do. The
    installer writes the flag too, but this function overwrites what the
    installer wrote whenever settings are saved, so leaving it out here
    silently undid it for anyone who ever opened the settings window.
    """
    executable = sys.executable
    if getattr(sys, "frozen", False):
        return f'"{executable}" --minimized'
    script = paths.resource_path("main.py")
    return f'"{executable}" "{script}" --minimized'


def autostart_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _RUN_VALUE)
            return bool(value)
    except OSError:
        return False


def _autostart_command() -> Optional[str]:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _RUN_VALUE)
            return str(value)
    except OSError:
        return None


def _autostart_target(command: str) -> str:
    """The executable a Run entry names, unquoted."""
    if not command.startswith('"'):
        return command.split(" ", 1)[0]
    end = command.find('"', 1)
    return command[1:end] if end > 0 else command[1:]


def repair_autostart() -> None:
    """Bring a stale login entry up to date. Two ways it goes stale.

    One: it was written before ``--minimized`` was included, so the app
    came up with its window over everything at every login.

    Two: it names an executable that is no longer there. Installs made
    when the app was called D1CT sat in a folder of that name, and the
    installer that finally moves them leaves any entry the user wrote
    from inside the app pointing at the old path.

    Repointing is only ever done by a frozen build: a copy run from a
    source checkout has no business aiming the installed app's autostart
    at a working directory.
    """
    current = _autostart_command()
    if current is None:
        return

    same_executable = f'"{sys.executable}"' in current
    if same_executable and "--minimized" in current:
        return

    orphaned = (getattr(sys, "frozen", False)
                and not os.path.exists(_autostart_target(current)))
    if not (same_executable or orphaned):
        return
    if set_autostart(True):
        log.info("Autostart entry repaired: %s -> %s", current, _launch_command())


def set_autostart(enabled: bool) -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            for legacy in _LEGACY_RUN_VALUES:
                try:
                    winreg.DeleteValue(key, legacy)
                except FileNotFoundError:
                    pass
            if enabled:
                winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, _launch_command())
            else:
                try:
                    winreg.DeleteValue(key, _RUN_VALUE)
                except FileNotFoundError:
                    pass
        return True
    except OSError as exc:
        log.warning("Could not update autostart: %s", exc)
        return False


# -- window plumbing -----------------------------------------------------

# Declared rather than left to ctypes' c_int default, so handles survive
# intact on a 64-bit build.
user32.GetForegroundWindow.restype = wt.HWND
user32.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
user32.RegisterWindowMessageW.restype = wt.UINT
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.restype = wt.BOOL
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
kernel32.CreateMutexW.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL


# -- single instance -----------------------------------------------------


class SingleInstance:
    """A named mutex, checked before the UI is built.

    macOS writes a PID file and signals the running control panel; the
    Windows equivalent is a kernel mutex plus a broadcast window message
    so a second launch surfaces the existing window instead of racing it
    for the keyboard hook.
    """

    def __init__(self, name: str = paths.SINGLE_INSTANCE_MUTEX) -> None:
        self._handle = kernel32.CreateMutexW(None, False, name)
        # ctypes saves and restores the thread's last-error value around
        # every call when the library was opened with use_last_error, so
        # calling GetLastError() through it reads back ctypes' own restored
        # value rather than CreateMutexW's. ctypes.get_last_error() is the
        # one that returns what the call actually set.
        self.already_running = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS

    def release(self) -> None:
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None


SHOW_PANEL_MESSAGE = "Lexomorph.ShowControlPanel"

# The identity Windows groups taskbar buttons and pinned shortcuts by. The
# installer stamps the same string onto the shortcuts it creates.
APP_USER_MODEL_ID = "local.Lexomorph"


def set_app_user_model_id(app_id: str = APP_USER_MODEL_ID) -> None:
    """Claim an explicit taskbar identity, before any window exists.

    Without one, Windows derives an identity from the executable path and
    keeps the icon it cached for it — which is why the tray, drawn by this
    process from the current artwork, updated after a rebrand while the
    taskbar button kept showing the old picture.
    """
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception as exc:  # pragma: no cover - shell32 is always there
        log.warning("Could not set the app user model id: %s", exc)


def register_show_message() -> int:
    return user32.RegisterWindowMessageW(SHOW_PANEL_MESSAGE)


def broadcast_show_panel() -> None:
    HWND_BROADCAST = 0xFFFF
    user32.PostMessageW(HWND_BROADCAST, register_show_message(), 0, 0)
