"""The press / release sequence, in the order the app runs it.

Kept free of Qt so ``--bench-record-latency`` measures exactly this code.

The stop cue is issued *before* the slow part of its step: closing a
WASAPI stream and resampling a long clip cost tens to hundreds of
milliseconds. The start cue is adaptive, see :func:`begin`.
"""

from __future__ import annotations

from typing import Callable, Optional


def begin(recorder, sounds, device: str,
          then: Optional[Callable[[], None]] = None) -> bool:
    """Start the microphone and the start cue, in the safe order.

    When capture will start about as fast as the cue (stream already
    open, or the last real open was quick) the cue goes out first and the
    two overlap. When opening is slow, or has never been measured, the cue
    waits until the stream is running, so hearing it guarantees that
    speaking is safe. ``then`` runs after the cue (the output mute). If the
    microphone cannot be opened the caller reports the error as usual.
    """
    if recorder.cue_before_open(device):
        sounds.play("start", then=then)
        return recorder.start(device)
    if not recorder.start(device):
        return False
    sounds.play("start", then=then)
    return True


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
