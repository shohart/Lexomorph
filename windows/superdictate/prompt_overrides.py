"""Account sync of the full system prompts of the built-in rewrite styles.

The user can replace the whole system prompt of ``polish``,
``structured_task`` and ``official`` in Settings; it is stored in
``rewrite_system_prompt_<style>_v1`` (``""`` = the built-in default). This
module syncs those overrides through the ``prompts`` collection of the
``/v1/vocabulary`` endpoint, on the model of
:class:`~superdictate.rewrite_styles.StyleStore`:

* a row is ``{"style", "prompt" (1..16000), "deleted", "updated_at"}``;
  ``deleted`` means "back to the built-in default" (the prompt may be empty);
* each style keeps a local stamp (``rewrite_system_prompt_sync_v1``); clearing
  a previously non-empty override leaves a tombstone, like a deleted mode;
* a non-empty override that has no stamp yet (written before sync existed) is
  stamped "now" the first time a pass looks at it, so existing edits upload;
* last write wins by ``updated_at``; on a tie the server's row wins;
* rows applied from the server notify as ``"sync"``, never ``"local"``, so
  they do not start another pass.

The text itself stays where the pipeline reads it
(``Settings.rewrite_config().system_prompt_overrides``). Both keys are in
``settings._RUNTIME_KEYS``: the settings window's draft never writes them (a
stale draft would roll a sync back); it calls :meth:`PromptOverrides.set_local`
for the styles the user actually changed.
"""

from __future__ import annotations

import threading
from typing import Callable, Iterable

from .logging_setup import get as get_logger
from .rewrite_styles import CHANGE_LOCAL, CHANGE_SYNC, EPOCH, _later, utc_now

log = get_logger("prompt_overrides")

STYLES = ("polish", "structured_task", "official")
MAX_PROMPT = 16000
STAMPS_KEY = "rewrite_system_prompt_sync_v1"


def prompt_key(style: str) -> str:
    return f"rewrite_system_prompt_{style}_v1"


class PromptOverrides:
    """The built-in styles' prompt overrides and their sync stamps."""

    def __init__(self, settings) -> None:
        self._settings = settings
        self._lock = threading.RLock()
        self._listeners: list[Callable[[str], None]] = []
        self._too_long_logged: set[str] = set()

    # -- listeners -----------------------------------------------------

    def add_listener(self, callback: Callable[[str], None]) -> None:
        self._listeners.append(callback)

    def _notify(self, kind: str) -> None:
        for callback in list(self._listeners):
            try:
                callback(kind)
            except Exception as exc:  # a listener must not break a write
                log.debug("Prompt listener failed: %s", exc)

    # -- reading -------------------------------------------------------

    def get(self, style: str) -> str:
        return str(self._settings._get(prompt_key(style)) or "")

    def _stamps(self) -> dict[str, dict]:
        raw = self._settings._get(STAMPS_KEY)
        result: dict[str, dict] = {}
        if isinstance(raw, dict):
            for style in STYLES:
                item = raw.get(style)
                if isinstance(item, dict) and item.get("updated_at"):
                    result[style] = {"updated_at": str(item["updated_at"]),
                                     "deleted": bool(item.get("deleted"))}
        return result

    def stamp(self, style: str) -> str:
        """The local stamp, ``EPOCH`` when there is none."""
        return self._stamps().get(style, {}).get("updated_at", EPOCH)

    def _save(self, stamps: dict[str, dict], texts: dict[str, str]) -> None:
        changes: dict = {STAMPS_KEY: stamps}
        for style, text in texts.items():
            changes[prompt_key(style)] = text
        self._settings.update_runtime(changes)

    # -- local edits ---------------------------------------------------

    def set_local(self, style: str, text: str) -> bool:
        """The user saved ``text`` (``""`` = reset to the built-in). Returns
        whether anything changed."""
        if style not in STYLES:
            raise KeyError(style)
        text = str(text).strip()
        with self._lock:
            current = self.get(style)
            if text == current:
                return False
            stamps = self._stamps()
            previous = stamps.get(style, {}).get("updated_at", EPOCH)
            if text:
                stamps[style] = {"updated_at": _later(previous), "deleted": False}
            elif current:
                stamps[style] = {"updated_at": _later(previous), "deleted": True}
            self._save(stamps, {style: text})
        self._notify(CHANGE_LOCAL)
        return True

    # -- sync ----------------------------------------------------------

    def _stamp_unstamped(self) -> None:
        """A non-empty override from before sync existed uploads once."""
        with self._lock:
            stamps = self._stamps()
            changed = False
            for style in STYLES:
                if self.get(style) and style not in stamps:
                    stamps[style] = {"updated_at": utc_now(), "deleted": False}
                    changed = True
            if changed:
                self._settings.update_runtime({STAMPS_KEY: stamps})

    def changes_since(self, stamp: str) -> list[dict]:
        """Wire rows stamped at or after ``stamp`` (``>=``, like the styles)."""
        self._stamp_unstamped()
        rows = []
        stamps = self._stamps()
        for style in STYLES:
            item = stamps.get(style)
            if item is None or item["updated_at"] < stamp:
                continue
            if item["deleted"] or not self.get(style):
                rows.append({"style": style, "prompt": "", "deleted": True,
                             "updated_at": item["updated_at"]})
                continue
            text = self.get(style)
            if len(text) > MAX_PROMPT:
                if style not in self._too_long_logged:
                    self._too_long_logged.add(style)
                    log.info("The %s prompt is %d characters, over the %d the server stores; "
                             "kept on this machine", style, len(text), MAX_PROMPT)
                continue
            rows.append({"style": style, "prompt": text, "deleted": False,
                         "updated_at": item["updated_at"]})
        return rows

    def apply_remote(self, entries: Iterable[dict]) -> int:
        """Merge the server's rows; returns how many changed anything here."""
        applied = 0
        with self._lock:
            stamps = self._stamps()
            texts: dict[str, str] = {}
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                style = str(entry.get("style") or "")
                stamp = str(entry.get("updated_at") or "")
                if style not in STYLES or not stamp:
                    continue
                known = stamps.get(style, {}).get("updated_at", EPOCH)
                if stamp < known:
                    continue  # edited here later; the next push sends ours
                before = texts.get(style, self.get(style))
                if entry.get("deleted"):
                    text, dead = "", True
                else:
                    text, dead = str(entry.get("prompt") or "").strip(), False
                    if not text or len(text) > MAX_PROMPT:
                        log.info("Ignoring a malformed prompt from the server (%s)", style)
                        continue
                if text != before or stamps.get(style) != {"updated_at": stamp, "deleted": dead}:
                    if text != before:
                        applied += 1
                    texts[style] = text
                    stamps[style] = {"updated_at": stamp, "deleted": dead}
            if texts or stamps != self._stamps():
                self._save(stamps, texts)
        if applied:
            self._notify(CHANGE_SYNC)
        return applied
