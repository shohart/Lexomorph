"""User-created rewrite modes and their account sync.

The Windows side of ``CustomRewriteStyle`` (macOS) and of the ``styles``
collection of ``server/vocab-sync`` (docs/specs/modes-and-usage-sync-spec.md
section 3.1).

* A style is ``id`` (``c-<uuid>``), ``name`` (1..40), ``color`` (``#RRGGBB``),
  ``instruction`` (the prompt, up to 4000) and ``updated_at`` (ISO-8601 UTC).
* **Local to this machine, never synced:** the activation ``hotkey`` (key
  codes differ per platform) and which style is selected
  (``rewrite_custom_style_id_v1``).
* Deleting leaves a tombstone ``(id, deleted_at)`` so the delete wins over
  an older copy still on another machine.
* Everything lives in :class:`~superdictate.settings.Settings`
  (``rewrite_custom_styles_v1`` / ``..._tombstones_v1``), written only
  through this store: the settings window's draft never carries them
  (``_RUNTIME_KEYS``), so a stale draft cannot roll a sync back.
* Styles applied from the server do not notify as ``"local"``, so they do
  not start another sync (the same rule as the vocabulary).
"""

from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

from .hotkeys import HotkeyChoice
from .logging_setup import get as get_logger

log = get_logger("rewrite_styles")

CHANGE_LOCAL = "local"
CHANGE_SYNC = "sync"

MAX_NAME = 40
MAX_INSTRUCTION = 4000
MAX_ID = 64
ID_PREFIX = "c-"
MAX_TOMBSTONES = 1000
EPOCH = "1970-01-01T00:00:00Z"

#: The macOS palette (``customStylePalette``), in the same order.
PALETTE = (
    "#0A84FF", "#34C759", "#FF9F0A", "#FF375F", "#BF5AF2",
    "#00C7BE", "#FFD60A", "#FF453A", "#5E5CE6", "#98989D",
)
DEFAULT_COLOR = PALETTE[0]

_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_STYLES_KEY = "rewrite_custom_styles_v1"
_TOMBSTONES_KEY = "rewrite_custom_style_tombstones_v1"
_ACTIVE_KEY = "rewrite_custom_style_id_v1"
_BUILTIN_KEY = "rewrite_style_v1"
FALLBACK_STYLE = "polish"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_style_id() -> str:
    return ID_PREFIX + str(uuid.uuid4())


def normalize_color(value: object, fallback: str = DEFAULT_COLOR) -> str:
    text = str(value or "").strip()
    return text.upper() if _COLOR.match(text) else fallback


def valid_id(value: object) -> bool:
    text = str(value or "")
    return (text.startswith(ID_PREFIX) and len(text) > len(ID_PREFIX)
            and len(text) <= MAX_ID and text.isprintable() and " " not in text)


@dataclass
class CustomStyle:
    id: str
    name: str
    instruction: str
    color: str = DEFAULT_COLOR
    updated_at: str = EPOCH
    #: Local only. ``None`` = not assigned.
    hotkey: Optional[HotkeyChoice] = None

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "instruction": self.instruction,
            "updated_at": self.updated_at,
            "hotkey": self.hotkey.to_json() if self.hotkey else None,
        }

    @staticmethod
    def from_json(raw: object) -> Optional["CustomStyle"]:
        if not isinstance(raw, dict) or not raw.get("id"):
            return None
        style_id = str(raw["id"])
        name = " ".join(str(raw.get("name", "")).split())[:MAX_NAME]
        hotkey = None
        stored = raw.get("hotkey")
        if isinstance(stored, dict):
            choice = HotkeyChoice.from_json(stored, HotkeyChoice(0, 0))
            hotkey = choice if choice.vk else None
        return CustomStyle(
            id=style_id,
            name=name,
            instruction=str(raw.get("instruction", ""))[:MAX_INSTRUCTION],
            color=normalize_color(raw.get("color")),
            updated_at=str(raw.get("updated_at") or EPOCH),
            hotkey=hotkey,
        )

    def wire(self) -> dict:
        return {"id": self.id, "name": self.name, "color": self.color,
                "instruction": self.instruction, "deleted": False,
                "updated_at": self.updated_at}


@dataclass(frozen=True)
class StyleTombstone:
    id: str
    deleted_at: str

    def wire(self) -> dict:
        return {"id": self.id, "name": "", "color": DEFAULT_COLOR,
                "instruction": "", "deleted": True, "updated_at": self.deleted_at}


def _sendable(style: CustomStyle) -> bool:
    return (valid_id(style.id) and 1 <= len(style.name) <= MAX_NAME
            and len(style.instruction) <= MAX_INSTRUCTION)


def validate(name: str, instruction: str) -> tuple[str, str]:
    """The cleaned ``(name, instruction)``; ``ValueError`` names what is wrong
    (``"name"`` or ``"instruction"``)."""
    clean_name = " ".join(str(name).split())
    if not clean_name or len(clean_name) > MAX_NAME:
        raise ValueError("name")
    clean_instruction = str(instruction).strip()
    if not clean_instruction or len(clean_instruction) > MAX_INSTRUCTION:
        raise ValueError("instruction")
    return clean_name, clean_instruction


def _later(previous: str) -> str:
    """Now, but never not-after ``previous``: two edits in one second must
    still order, or the older copy could win the sync."""
    now = utc_now()
    if now > previous:
        return now
    try:
        stamp = datetime.strptime(previous, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return now
    return datetime.fromtimestamp(stamp.replace(tzinfo=timezone.utc).timestamp() + 1,
                                  timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class StyleStore:
    """The list of custom styles, persisted in the settings."""

    def __init__(self, settings) -> None:
        self._settings = settings
        self._lock = threading.RLock()
        self._listeners: list[Callable[[str], None]] = []

    # -- listeners -------------------------------------------------------

    def add_listener(self, callback: Callable[[str], None]) -> None:
        self._listeners.append(callback)

    def _notify(self, kind: str) -> None:
        for callback in list(self._listeners):
            try:
                callback(kind)
            except Exception as exc:  # a listener must not break a write
                log.debug("Style listener failed: %s", exc)

    # -- reading ---------------------------------------------------------

    def all(self) -> list[CustomStyle]:
        raw = self._settings._get(_STYLES_KEY)
        styles: list[CustomStyle] = []
        seen: set[str] = set()
        if isinstance(raw, list):
            for item in raw:
                style = CustomStyle.from_json(item)
                if style is not None and style.id not in seen:
                    seen.add(style.id)
                    styles.append(style)
        return styles

    def get(self, style_id: str) -> Optional[CustomStyle]:
        for style in self.all():
            if style.id == style_id:
                return style
        return None

    def tombstones(self) -> list[StyleTombstone]:
        raw = self._settings._get(_TOMBSTONES_KEY)
        result = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("id"):
                    result.append(StyleTombstone(str(item["id"]),
                                                 str(item.get("deleted_at") or EPOCH)))
        return result

    def hotkey_taken(self, choice: HotkeyChoice, *, except_id: str = "") -> Optional[CustomStyle]:
        """The other style that already uses ``choice``, if any."""
        for style in self.all():
            if style.id != except_id and style.hotkey == choice:
                return style
        return None

    # -- writing ---------------------------------------------------------

    def _save(self, styles: list[CustomStyle], tombstones: list[StyleTombstone]) -> None:
        tombstones = tombstones[-MAX_TOMBSTONES:]
        self._settings.update_runtime({
            _STYLES_KEY: [style.to_json() for style in styles],
            _TOMBSTONES_KEY: [{"id": t.id, "deleted_at": t.deleted_at} for t in tombstones],
        })

    def create(self, name: str, instruction: str, color: str = DEFAULT_COLOR,
               hotkey: Optional[HotkeyChoice] = None) -> CustomStyle:
        name, instruction = validate(name, instruction)
        with self._lock:
            style = CustomStyle(new_style_id(), name, instruction,
                                normalize_color(color), utc_now(), hotkey)
            self._save(self.all() + [style], self.tombstones())
        self._notify(CHANGE_LOCAL)
        return style

    def update(self, style_id: str, name: str, instruction: str, color: str,
               hotkey: Optional[HotkeyChoice]) -> CustomStyle:
        name, instruction = validate(name, instruction)
        with self._lock:
            styles = self.all()
            for index, style in enumerate(styles):
                if style.id != style_id:
                    continue
                changed = (style.name, style.instruction, style.color) != (
                    name, instruction, normalize_color(color))
                styles[index] = CustomStyle(
                    style_id, name, instruction, normalize_color(color),
                    _later(style.updated_at) if changed else style.updated_at, hotkey)
                self._save(styles, self.tombstones())
                result = styles[index]
                break
            else:
                raise KeyError(style_id)
        self._notify(CHANGE_LOCAL)
        return result

    def delete(self, style_id: str) -> bool:
        with self._lock:
            styles = self.all()
            remaining = [s for s in styles if s.id != style_id]
            if len(remaining) == len(styles):
                return False
            previous = next(s.updated_at for s in styles if s.id == style_id)
            tombstones = [t for t in self.tombstones() if t.id != style_id]
            tombstones.append(StyleTombstone(style_id, _later(previous)))
            self._save(remaining, tombstones)
            self._drop_active(style_id)
        self._notify(CHANGE_LOCAL)
        return True

    def _drop_active(self, style_id: str) -> None:
        """Deleting the selected mode falls back to ``polish``."""
        if str(self._settings._get(_ACTIVE_KEY) or "") == style_id:
            self._settings.update_runtime({_ACTIVE_KEY: "", _BUILTIN_KEY: FALLBACK_STYLE})

    def set_hotkey(self, style_id: str, hotkey: Optional[HotkeyChoice]) -> None:
        with self._lock:
            styles = self.all()
            for style in styles:
                if style.id == style_id:
                    style.hotkey = hotkey
                    break
            else:
                return
            self._save(styles, self.tombstones())
        self._notify(CHANGE_LOCAL)

    # -- sync ------------------------------------------------------------

    def changes_since(self, stamp: str) -> list[dict]:
        """Wire rows (live and deleted) stamped at or after ``stamp``.

        ``>=`` and not ``>``: a row stamped in the very second a pass began
        must not be missed, and re-sending one is harmless (last write wins,
        the server wins ties).
        """
        rows = [s.wire() for s in self.all() if _sendable(s) and s.updated_at >= stamp]
        rows += [t.wire() for t in self.tombstones()
                 if valid_id(t.id) and t.deleted_at >= stamp]
        return rows

    def apply_remote(self, entries: Iterable[dict]) -> int:
        """Merge the server's rows; returns how many changed anything here.

        Last write wins by ``updated_at``; on a tie the server's copy wins
        (the server's own rule), which makes every machine converge. The
        local hotkey is kept; a new style starts without one.
        """
        applied = 0
        with self._lock:
            styles = {s.id: s for s in self.all()}
            order = list(styles)
            tombstones = {t.id: t for t in self.tombstones()}
            active_deleted = False
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                style_id = str(entry.get("id") or "")
                stamp = str(entry.get("updated_at") or "")
                if not valid_id(style_id) or not stamp:
                    continue
                local = styles.get(style_id)
                dead = tombstones.get(style_id)
                if entry.get("deleted"):
                    if local is not None and stamp >= local.updated_at:
                        del styles[style_id]
                        order.remove(style_id)
                        active_deleted = active_deleted or style_id == str(
                            self._settings._get(_ACTIVE_KEY) or "")
                        tombstones[style_id] = StyleTombstone(style_id, stamp)
                        applied += 1
                    elif local is None and (dead is None or stamp > dead.deleted_at):
                        tombstones[style_id] = StyleTombstone(style_id, stamp)
                    continue
                name = " ".join(str(entry.get("name", "")).split())
                instruction = str(entry.get("instruction", "")).strip()
                color = entry.get("color")
                if not (1 <= len(name) <= MAX_NAME) or len(instruction) > MAX_INSTRUCTION \
                        or not _COLOR.match(str(color or "")):
                    log.info("Ignoring a malformed style from the server (%s)", style_id)
                    continue
                if dead is not None and stamp <= dead.deleted_at:
                    continue  # deleted here later than that edit
                if local is not None and stamp < local.updated_at:
                    continue
                new = CustomStyle(style_id, name, instruction, normalize_color(color), stamp,
                                  local.hotkey if local else None)
                if local is None:
                    order.append(style_id)
                    applied += 1
                elif (local.name, local.instruction, local.color, local.updated_at) != (
                        new.name, new.instruction, new.color, new.updated_at):
                    applied += 1
                styles[style_id] = new
                tombstones.pop(style_id, None)
            if applied or active_deleted:
                self._save([styles[i] for i in order], list(tombstones.values()))
            elif {t.id for t in self.tombstones()} != set(tombstones):
                self._save([styles[i] for i in order], list(tombstones.values()))
            if active_deleted:
                self._drop_active(str(self._settings._get(_ACTIVE_KEY) or ""))
        if applied:
            self._notify(CHANGE_SYNC)
        return applied
