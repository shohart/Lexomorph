"""``python main.py --bench-record-latency [runs] [device]``

Measures what the user feels between pressing the record hotkey and hearing
the start cue / having the microphone open, and the same for stop. It drives
the real :class:`~superdictate.audio.Recorder` and
:class:`~superdictate.system.Sounds` in the order the app uses
(:func:`superdictate.recording_flow.begin` / ``end``), with
``time.perf_counter_ns`` marks, and wraps ``winsound.PlaySound`` to see the
moment the cue is actually handed to Windows. No window, no hook, no model.

The real keystroke -> Qt-thread hop and the audible device latency are not
included (they cannot be seen from a script); the report says so.
"""

from __future__ import annotations

import statistics
import sys
import time

from . import audio, system

NS = 1_000_000.0


def _install_playsound_probe(marks: dict[str, list[int]]) -> None:
    import winsound

    real = winsound.PlaySound

    def probe(sound, flags):
        marks.setdefault("play_enter", []).append(time.perf_counter_ns())
        try:
            return real(sound, flags)
        finally:
            marks.setdefault("play_exit", []).append(time.perf_counter_ns())

    winsound.PlaySound = probe


# Defaults are WASAPI *output* shared-mode figures measured on the dev machine
# (open ~35 ms, close ~40 ms), the closest real endpoint it has.
_FAKE = {"rate": 48000, "open_ms": 35.0, "close_ms": 40.0}


class _FakeStream:
    """Stands in for ``sd.InputStream`` on a machine with no capture endpoint.

    Delivers 32 ms blocks from a thread, the first one 32 ms after start().
    It proves nothing about real device open time; it keeps the rest of the
    path (device lookup, pending file, cue) measurable.
    """

    def __init__(self, samplerate, blocksize, callback, **_kw):
        import threading
        import numpy as np

        if samplerate != _FAKE["rate"]:
            time.sleep(0.002)
            raise RuntimeError("Invalid sample rate")
        time.sleep(_FAKE["open_ms"] / 1000)
        self._rate, self._block, self._cb = samplerate, blocksize, callback
        self._np = np
        self._alive = threading.Event()
        self._thread = threading.Thread(target=self._pump, daemon=True)

    def start(self):
        self._alive.set()
        self._thread.start()

    def _pump(self):
        data = self._np.zeros((self._block, 1), dtype="float32")
        while self._alive.is_set():
            time.sleep(self._block / self._rate)
            self._cb(data, self._block, None, None)

    def stop(self):
        self._alive.clear()

    def close(self):
        self._alive.clear()
        time.sleep(_FAKE["close_ms"] / 1000)


def _install_fake_mic() -> None:
    import sounddevice as sd

    sd.InputStream = _FakeStream
    audio.device_sample_rate = lambda index: _FAKE["rate"]
    audio.resolve_device = lambda name: None


def _row(name: str, values: list[float]) -> str:
    if not values:
        return f"{name:<44}  n/a"
    ordered = sorted(values)
    p90 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))]
    return (f"{name:<44}  median {statistics.median(values):7.1f}  "
            f"p90 {p90:7.1f}  max {max(values):7.1f} ms")


def _legacy_begin(recorder, sounds, device):
    """The order before the fix: cue only after the stream is open."""
    if not recorder.start(device):
        return False
    sounds.play("start")
    return True


def _legacy_end(recorder, sounds):
    """The order before the fix: cue only after close + resample."""
    samples = recorder.stop()
    sounds.play("stop")
    return samples


def run(argv: list[str]) -> int:
    from . import recording_flow

    fake = "--fake-mic" in argv
    legacy = "--legacy-order" in argv
    for flag, key in (("--open-ms", "open_ms"), ("--close-ms", "close_ms")):
        if flag in argv:
            i = argv.index(flag)
            _FAKE[key] = float(argv[i + 1])
            del argv[i:i + 2]
    argv = [a for a in argv if a not in ("--fake-mic", "--legacy-order")]
    runs = int(argv[0]) if argv and argv[0].isdigit() else 20
    device = argv[1] if len(argv) > 1 and not argv[1].isdigit() else ""
    hold = 1.0
    if fake:
        _install_fake_mic()

    recorder = audio.Recorder()
    sounds = system.Sounds(True)
    marks: dict[str, list[int]] = {}
    _install_playsound_probe(marks)

    cols: dict[str, list[float]] = {k: [] for k in (
        "start: handler -> start cue handed to Windows",
        "start: handler -> recorder.start() returned",
        "start: handler -> first audio block",
        "start: Qt-thread time spent in handler",
        "stop:  handler -> stop cue handed to Windows",
        "stop:  Qt-thread time spent in handler",
        "start: resolve+rate query",
        "start: InputStream() construct",
        "start: stream.start()",
        "stop:  stream stop+close",
    )}
    failures = 0
    for i in range(runs):
        marks.clear()
        t0 = time.perf_counter_ns()
        ok = (_legacy_begin if legacy else recording_flow.begin)(recorder, sounds, device)
        t_ret = time.perf_counter_ns()
        if not ok:
            failures += 1
            print(f"run {i}: could not open the microphone: {recorder.last_error}")
            continue
        deadline = time.monotonic() + 3
        while "first_block" not in recorder.trace and time.monotonic() < deadline:
            time.sleep(0.001)
        tr = dict(recorder.trace)
        start_play = marks.get("play_enter", [None])[0]
        cols["start: handler -> start cue handed to Windows"].append(
            ((start_play or t0) - t0) / NS)
        cols["start: handler -> recorder.start() returned"].append(
            (tr["start_return"] - t0) / NS)
        if "first_block" in tr:
            cols["start: handler -> first audio block"].append((tr["first_block"] - t0) / NS)
        cols["start: Qt-thread time spent in handler"].append((t_ret - t0) / NS)
        cols["start: resolve+rate query"].append((tr["rate_known"] - tr["start_call"]) / NS)
        cols["start: InputStream() construct"].append(
            (tr["stream_created"] - tr["rate_known"]) / NS)
        cols["start: stream.start()"].append((tr["stream_started"] - tr["stream_created"]) / NS)

        time.sleep(hold)
        marks.clear()
        s0 = time.perf_counter_ns()
        (_legacy_end if legacy else recording_flow.end)(recorder, sounds)
        s_ret = time.perf_counter_ns()
        time.sleep(0.15)  # let the cue thread reach PlaySound
        stop_play = marks.get("play_enter", [None])[0]
        cols["stop:  handler -> stop cue handed to Windows"].append(
            ((stop_play or s0) - s0) / NS)
        cols["stop:  Qt-thread time spent in handler"].append((s_ret - s0) / NS)
        tr = recorder.trace
        if "stream_closed" in tr:
            cols["stop:  stream stop+close"].append(
                (tr["stream_closed"] - tr["stop_call"]) / NS)
        time.sleep(0.4)  # let the cue finish before the next round

    print(f"record-latency bench, {runs} runs, device={device or 'system default'}, "
          f"{('FAKE MIC open=%gms close=%gms' % (_FAKE['open_ms'], _FAKE['close_ms'])) if fake else 'real mic'}, {'legacy order' if legacy else 'current order'}, {failures} failed")
    for name, values in cols.items():
        print(_row(name, values))
    print("Not covered: hotkey hook -> Qt thread hop, audible output device latency.")
    return 1 if failures == runs else 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
