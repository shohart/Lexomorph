"""Transcript history and daily usage statistics.

macOS keeps both inside NSUserDefaults (``recent_transcript_entries_v1``
and ``daily_dictation_usage_v1``). Here they are separate JSON files so a
long history never bloats the settings file the app rewrites on every
preference change.

The archive keeps up to 200 entries regardless of the user's "show last N"
preference, the preference controls what the quick-history window offers
for re-insertion, not how much is retained, exactly as on macOS.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from . import paths
from .logging_setup import get as get_logger
from .settings import HISTORY_ARCHIVE_MAX_ENTRIES

log = get_logger("history")


@dataclass
class HistoryEntry:
    text: str
    created_at: float
    audio_seconds: float = 0.0
    transcription_seconds: float = 0.0

    def to_json(self) -> dict:
        return {
            "text": self.text,
            "created_at": self.created_at,
            "audio_seconds": self.audio_seconds,
            "transcription_seconds": self.transcription_seconds,
        }

    @staticmethod
    def from_json(raw: object) -> Optional["HistoryEntry"]:
        if not isinstance(raw, dict):
            return None
        text = str(raw.get("text", "")).strip()
        if not text:
            return None
        try:
            return HistoryEntry(
                text=text,
                created_at=float(raw.get("created_at", 0.0)),
                audio_seconds=float(raw.get("audio_seconds", 0.0)),
                transcription_seconds=float(raw.get("transcription_seconds", 0.0)),
            )
        except (TypeError, ValueError):
            return None


def _write_json(path, payload) -> None:
    paths.ensure_directories()
    temp = f"{path}.tmp"
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    except OSError as exc:
        log.warning("Could not write %s: %s", path, exc)
        try:
            os.unlink(temp)
        except OSError:
            pass


def _read_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return fallback


class History:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: list[HistoryEntry] = []
        self.load()

    def load(self) -> None:
        raw = _read_json(paths.HISTORY_FILE, [])
        if not isinstance(raw, list):
            return
        entries = [entry for entry in (HistoryEntry.from_json(item) for item in raw)
                   if entry is not None]
        with self._lock:
            self._entries = entries[:HISTORY_ARCHIVE_MAX_ENTRIES]

    def save(self) -> None:
        with self._lock:
            payload = [entry.to_json() for entry in self._entries]
        _write_json(paths.HISTORY_FILE, payload)

    def add(self, entry: HistoryEntry) -> None:
        with self._lock:
            self._entries.insert(0, entry)
            del self._entries[HISTORY_ARCHIVE_MAX_ENTRIES:]
        self.save()

    def entries(self, limit: Optional[int] = None) -> list[HistoryEntry]:
        with self._lock:
            items = list(self._entries)
        return items if limit is None else items[:limit]

    def clear(self) -> None:
        with self._lock:
            self._entries = []
        self.save()

    def amend(self, original: str, text: str) -> bool:
        """Rewrite the newest entry, provided it is still ``original``.

        The transcript editor corrects the dictation that just happened.
        If another one has landed in the meantime the archive is left
        alone rather than rewriting whichever entry is now on top.
        """
        with self._lock:
            if not self._entries or self._entries[0].text != original:
                return False
            self._entries[0].text = text
        self.save()
        return True

    def remove(self, index: int) -> None:
        with self._lock:
            if 0 <= index < len(self._entries):
                del self._entries[index]
        self.save()


@dataclass
class DailyUsage:
    day: str  # ISO date
    dictations: int = 0
    audio_seconds: float = 0.0
    characters: int = 0
    words: int = 0
    #: Only filled by another device's row (macOS counts it, we do not).
    asr_seconds: float = 0.0
    #: ISO-8601 UTC of the last change; the sync's last-write-wins key.
    updated_at: str = ""

    def to_json(self) -> dict:
        return {
            "day": self.day,
            "dictations": self.dictations,
            "audio_seconds": self.audio_seconds,
            "characters": self.characters,
            "words": self.words,
            "updated_at": self.updated_at,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_day(item: object) -> Optional[DailyUsage]:
    if not isinstance(item, dict):
        return None
    day = str(item.get("day", ""))
    if not _valid_day(day):
        return None
    try:
        return DailyUsage(
            day=day,
            dictations=max(0, int(item.get("dictations", 0))),
            audio_seconds=max(0.0, float(item.get("audio_seconds", 0.0))),
            characters=max(0, int(item.get("characters", 0))),
            words=max(0, int(item.get("words", 0))),
            asr_seconds=max(0.0, float(item.get("asr_seconds") or 0.0)),
            updated_at=str(item.get("updated_at") or ""),
        )
    except (TypeError, ValueError, OverflowError):
        return None


def _valid_day(day: str) -> bool:
    try:
        return len(day) == 10 and date.fromisoformat(day).isoformat() == day
    except ValueError:
        return False


class UsageStats:
    """Per-day dictation counters, kept for a rolling year.

    With account sync (docs/specs/modes-and-usage-sync-spec.md 3.2) there
    are two kinds of rows. **This device's** days are counted here and sent
    as absolute values (``own_rows_since``): re-sending is idempotent, so
    nothing is ever counted twice. **Other devices'** rows come back from
    the server and are kept apart (``UsageSync.json``), never mixed into
    the local counters; ``all_days`` / ``today`` / ``totals`` show the sum
    over all devices. Our own row is read from the local counter, never
    from the server's echo.
    """

    MAX_DAYS = 400

    def __init__(self, sync_path=None) -> None:
        self._lock = threading.RLock()
        self._days: dict[str, DailyUsage] = {}
        self._sync_path = sync_path if sync_path is not None else paths.USAGE_SYNC_FILE
        self._device = ""
        #: (day, device) -> row, other devices only.
        self._remote: dict[tuple[str, str], DailyUsage] = {}
        self.load()

    def load(self) -> None:
        raw = _read_json(paths.USAGE_FILE, [])
        days: dict[str, DailyUsage] = {}
        if isinstance(raw, list):
            for item in raw:
                usage = _parse_day(item)
                if usage is None:
                    continue
                # Days counted before the sync existed get a stamp that
                # sorts before any real edit.
                usage.updated_at = usage.updated_at or f"{usage.day}T00:00:00Z"
                days[usage.day] = usage
        sync = _read_json(self._sync_path, {})
        device = ""
        remote: dict[tuple[str, str], DailyUsage] = {}
        if isinstance(sync, dict):
            device = str(sync.get("device") or "")[:64]
            for item in sync.get("rows") or []:
                usage = _parse_day(item)
                owner = str(item.get("device") or "")[:64] if isinstance(item, dict) else ""
                if usage is not None and owner and owner != device:
                    remote[(usage.day, owner)] = usage
        with self._lock:
            self._days = days
            self._device = device
            self._remote = remote

    def save(self) -> None:
        with self._lock:
            items = sorted(self._days.values(), key=lambda d: d.day, reverse=True)
            items = items[: self.MAX_DAYS]
            self._days = {item.day: item for item in items}
            payload = [item.to_json() for item in items]
        _write_json(paths.USAGE_FILE, payload)

    def _save_sync(self) -> None:
        with self._lock:
            payload = {"device": self._device, "rows": [
                {**usage.to_json(), "device": owner, "asr_seconds": usage.asr_seconds}
                for (_, owner), usage in sorted(self._remote.items())]}
        _write_json(self._sync_path, payload)

    def record(self, text: str, audio_seconds: float, when: Optional[datetime] = None) -> None:
        day = (when or datetime.now()).date().isoformat()
        with self._lock:
            usage = self._days.setdefault(day, DailyUsage(day))
            usage.dictations += 1
            usage.audio_seconds += audio_seconds
            usage.characters += len(text)
            usage.words += len(text.split())
            usage.updated_at = _utc_now()
        self.save()

    # -- this device -----------------------------------------------------

    def device_id(self) -> str:
        """This device's random id, made on first use and kept."""
        with self._lock:
            if not self._device:
                self._device = str(uuid.uuid4())
                created = True
            else:
                created = False
        if created:
            self._save_sync()
        return self._device

    def own_rows_since(self, stamp: str) -> list[dict]:
        """This device's days changed at or after ``stamp``, as wire rows
        with absolute values (the last ``MAX_DAYS`` days)."""
        device = self.device_id()
        with self._lock:
            days = sorted(self._days.values(), key=lambda d: d.day, reverse=True)[: self.MAX_DAYS]
            return [{
                "day": u.day, "device": device, "dictations": u.dictations,
                "characters": u.characters, "words": u.words,
                "audio_seconds": float(u.audio_seconds), "asr_seconds": 0.0,
                "updated_at": u.updated_at,
            } for u in days if u.updated_at >= stamp and u.dictations > 0]

    # -- other devices ---------------------------------------------------

    def apply_remote(self, rows: list) -> int:
        """Keep the other devices' rows (last write wins per day and device).
        Rows of this device are ignored: its counter is the truth."""
        own = self.device_id()
        changed = 0
        with self._lock:
            for item in rows:
                usage = _parse_day(item)
                owner = str(item.get("device") or "")[:64] if isinstance(item, dict) else ""
                if usage is None or not owner or owner == own or not usage.updated_at:
                    continue
                key = (usage.day, owner)
                known = self._remote.get(key)
                if known is not None and usage.updated_at < known.updated_at:
                    continue
                if known is None or known.to_json() != usage.to_json() \
                        or known.asr_seconds != usage.asr_seconds:
                    self._remote[key] = usage
                    changed += 1
            if changed:
                self._trim_remote()
        if changed:
            self._save_sync()
        return changed

    def _trim_remote(self) -> None:
        by_device: dict[str, list[tuple[str, str]]] = {}
        for key in self._remote:
            by_device.setdefault(key[1], []).append(key)
        for keys in by_device.values():
            for key in sorted(keys, reverse=True)[self.MAX_DAYS:]:
                del self._remote[key]

    def forget_remote(self) -> None:
        """Signed out or another account: the other devices' rows go."""
        with self._lock:
            had = bool(self._remote)
            self._remote = {}
        if had:
            self._save_sync()

    def has_remote(self) -> bool:
        with self._lock:
            return bool(self._remote)

    # -- the sum over all devices ---------------------------------------

    def all_days(self) -> list[DailyUsage]:
        with self._lock:
            merged: dict[str, DailyUsage] = {}
            for usage in list(self._days.values()) + list(self._remote.values()):
                total = merged.setdefault(usage.day, DailyUsage(usage.day))
                total.dictations += usage.dictations
                total.audio_seconds += usage.audio_seconds
                total.characters += usage.characters
                total.words += usage.words
                total.asr_seconds += usage.asr_seconds
            return sorted(merged.values(), key=lambda d: d.day, reverse=True)

    def today(self) -> DailyUsage:
        day = date.today().isoformat()
        for usage in self.all_days():
            if usage.day == day:
                return usage
        return DailyUsage(day)

    def totals(self) -> DailyUsage:
        total = DailyUsage("all")
        for usage in self.all_days():
            total.dictations += usage.dictations
            total.audio_seconds += usage.audio_seconds
            total.characters += usage.characters
            total.words += usage.words
            total.asr_seconds += usage.asr_seconds
        return total


class Corrections:
    """The user's replacement dictionary, stored separately so it can be
    hand-edited or synced between machines like the macOS sync file."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: list = []
        self.load()

    def load(self) -> None:
        from .settings import Correction

        raw = _read_json(paths.CORRECTIONS_FILE, [])
        items = []
        if isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                source = str(entry.get("source", "")).strip()
                replacement = str(entry.get("replacement", "")).strip()
                if source and replacement:
                    items.append(Correction(source, replacement))
        with self._lock:
            self._items = items

    def save(self) -> None:
        with self._lock:
            payload = [item.to_json() for item in self._items]
        _write_json(paths.CORRECTIONS_FILE, payload)

    def all(self) -> list:
        with self._lock:
            return list(self._items)

    def learn(self, pairs) -> int:
        """Record (heard, meant) pairs, one rule per source word.

        A second correction of the same word is the user changing their
        mind, not a second rule: the existing entry is rewritten in place
        so the dictionary cannot end up with two answers for one input.
        """
        from .settings import Correction

        learned = 0
        with self._lock:
            for raw_source, raw_replacement in pairs:
                source = " ".join(str(raw_source).split())
                replacement = " ".join(str(raw_replacement).split())
                if not source or not replacement:
                    continue
                key = source.casefold()
                for index, item in enumerate(self._items):
                    if item.source.casefold() == key:
                        self._items[index] = Correction(source, replacement)
                        break
                else:
                    self._items.append(Correction(source, replacement))
                learned += 1
        if learned:
            self.save()
        return learned

    def replace_all(self, items) -> None:
        with self._lock:
            self._items = list(items)
        self.save()
