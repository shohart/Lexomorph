"""The press / release sequence, in the order the app runs it.

Kept free of Qt so ``--bench-record-latency`` measures exactly this code.

Both cues are issued *before* the slow part of their step. Opening a
WASAPI input stream and closing it again (plus resampling a long clip)
cost tens to hundreds of milliseconds, and the user hears the cue as "it
registered my key"; it must not wait for them.
"""

from __future__ import annotations

from typing import Callable, Optional


def begin(recorder, sounds, device: str,
          then: Optional[Callable[[], None]] = None) -> bool:
    """Start the start cue, then open the microphone.

    The cue plays on its own thread, so both proceed in parallel. ``then``
    runs after the cue (the output mute). If the microphone cannot be
    opened the caller reports the error as usual.
    """
    sounds.play("start", then=then)
    return recorder.start(device)


def end(recorder, sounds, restore: Optional[Callable[[], None]] = None):
    """Freeze the clip, play the stop cue, then close the stream.

    ``restore`` undoes the output mute first, otherwise the cue would be
    played into a muted device.
    """
    recorder.halt()
    if restore is not None:
        restore()
    sounds.play("stop")
    return recorder.stop()
