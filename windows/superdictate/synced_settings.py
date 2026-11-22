"""Account sync stores for filler words (`fillers`) and cross-platform
preferences (`prefs`).

Both follow the exact wire contract of ``server/vocab-sync/app.py`` and the
macOS ``Settings`` sync helpers:

* **Fresh-install safety:** only values explicitly edited locally get a sync
  stamp, so a newly installed PC signing into an existing account pulls the
  account's saved fillers and preferences without overwriting them with
  factory defaults.
* **LWW + tombstones:** last write wins on ``updated_at`` (ties go to the
  server copy). Remote applications notify as ``"sync"``, never ``"local"``,
  so they never trigger a sync loop.
"""

from __future__ import annotations

import threading
import time
import unicodedata
from typing import Callable, Iterable, Optional

from .logging_setup import get as get_logger
from .textproc import PRESET_FILLERS

log = get_logger("synced_settings")

CHANGE_LOCAL = "local"
CHANGE_SYNC = "sync"
EPOCH = "1970-01-01T00:00:00Z"

FILLER_STAMPS_KEY = "filler_sync_stamps_v1"
FILLER_TOMBSTONES_KEY = "filler_sync_tombstones_v1"
FILLER_CUSTOM_KEY = "filler_custom_words_v1"
PREF_STAMPS_KEY = "synced_pref_stamps_v1"

_PRESET_BY_NORM = {
    " ".join(unicodedata.normalize("NFC", word).casefold().split()): word
    for word, _ in PRESET_FILLERS
}

# Mapping: wire key <-> local settings key, plus kind ("bool" | "str").
PREF_SPEC: dict[str, tuple[str, str]] = {
    "remove_filler_words": ("remove_filler_words", "bool"),
    "normalize_numbers": ("numbers_as_digits", "bool"),
    "remove_final_period": ("remove_final_period", "bool"),
    "paste_suffix": ("paste_suffix", "str"),
    "dictation_language": ("dictation_language", "str"),
    "auto_learn_vocabulary": ("auto_learn_vocabulary", "bool"),
    "asr_hotwords_enabled": ("asr_hotwords_enabled", "bool"),
    "asr_hotwords_strength": ("asr_hotwords_strength", "str"),
    "interface_language": ("interface_language", "str"),
}

_VALID_STR_PREFS: dict[str, frozenset[str]] = {
    "paste_suffix": frozenset({"none", "space", "newline"}),
    "asr_hotwords_strength": frozenset({"normal", "strong"}),
    "interface_language": frozenset({"ru", "en", "auto"}),
}


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _later(previous: str) -> str:
    now = utc_now()
    if not previous or now > previous:
        return now
    # Bump by 1 second if two edits land inside the same UTC second.
    try:
        t = time.strptime(previous, "%Y-%m-%dT%H:%M:%SZ")
        import calendar
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(calendar.timegm(t) + 1))
    except Exception:
        return now


def normalized_filler_key(word: str) -> str:
    return " ".join(unicodedata.normalize("NFC", str(word)).casefold().split())


class FillerSync:
    """Syncs filler word preset toggles and custom filler words (`fillers`)."""

    def __init__(self, settings) -> None:
        self._settings = settings
        self._lock = threading.RLock()
        self._listeners: list[Callable[[str], None]] = []

    def add_listener(self, callback: Callable[[str], None]) -> None:
        self._listeners.append(callback)

    def _notify(self, kind: str) -> None:
        for cb in list(self._listeners):
            try:
                cb(kind)
            except Exception as exc:
                log.debug("FillerSync listener failed: %s", exc)

    def _stamps(self) -> dict[str, str]:
        raw = self._settings._get(FILLER_STAMPS_KEY)
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items() if k and v}

    def _tombstones(self) -> list[dict[str, str]]:
        raw = self._settings._get(FILLER_TOMBSTONES_KEY)
        if not isinstance(raw, list):
            return []
        result = []
        for item in raw:
            if isinstance(item, dict) and item.get("word") and item.get("deleted_at"):
                result.append({"word": str(item["word"]), "deleted_at": str(item["deleted_at"])})
        return result

    def _custom_words(self) -> list[str]:
        stored = [str(w) for w in (self._settings._get(FILLER_CUSTOM_KEY) or []) if str(w).strip()]
        enabled = [str(w) for w in (self._settings._get("filler_words") or []) if str(w).strip()]
        seen = {normalized_filler_key(w) for w in stored}
        out = list(stored)
        for w in enabled:
            norm = normalized_filler_key(w)
            if norm not in _PRESET_BY_NORM and norm not in seen:
                out.append(w)
                seen.add(norm)
        return out

    def record_local_change(self, before_enabled: Iterable[str], after_enabled: Iterable[str],
                            before_custom: Optional[Iterable[str]] = None,
                            after_custom: Optional[Iterable[str]] = None) -> bool:
        """Stamp every filler word whose enabled or presence state changed."""
        b_en = {normalized_filler_key(w): w for w in before_enabled if normalized_filler_key(w)}
        a_en = {normalized_filler_key(w): w for w in after_enabled if normalized_filler_key(w)}

        b_cu = ({normalized_filler_key(w): w for w in before_custom if normalized_filler_key(w)}
                if before_custom is not None
                else {k: v for k, v in b_en.items() if k not in _PRESET_BY_NORM})
        a_cu = ({normalized_filler_key(w): w for w in after_custom if normalized_filler_key(w)}
                if after_custom is not None
                else {k: v for k, v in a_en.items() if k not in _PRESET_BY_NORM})

        changed = False
        with self._lock:
            stamps = self._stamps()
            tombstones = self._tombstones()

            # Toggled presets or custom words.
            for norm in set(b_en.keys()) ^ set(a_en.keys()):
                if norm in _PRESET_BY_NORM or norm in a_cu:
                    prev = stamps.get(norm, EPOCH)
                    stamps[norm] = _later(prev)
                    tombstones = [t for t in tombstones if normalized_filler_key(t["word"]) != norm]
                    changed = True

            # Newly added custom words (even if unticked).
            for norm in set(a_cu.keys()) - set(b_cu.keys()):
                prev = stamps.get(norm, EPOCH)
                stamps[norm] = _later(prev)
                tombstones = [t for t in tombstones if normalized_filler_key(t["word"]) != norm]
                changed = True

            # Explicitly removed custom words -> tombstones.
            for norm in set(b_cu.keys()) - set(a_cu.keys()):
                prev = stamps.pop(norm, EPOCH)
                tombstones = [t for t in tombstones if normalized_filler_key(t["word"]) != norm]
                tombstones.append({"word": b_cu[norm], "deleted_at": _later(prev)})
                changed = True

            if changed:
                tombstones = sorted(tombstones, key=lambda t: t["deleted_at"])[-1000:]
                self._settings.update_runtime({
                    FILLER_STAMPS_KEY: stamps,
                    FILLER_TOMBSTONES_KEY: tombstones,
                    FILLER_CUSTOM_KEY: list(a_cu.values()),
                })
        if changed:
            self._notify(CHANGE_LOCAL)
        return changed

    def changes_since(self, stamp: str) -> list[dict]:
        with self._lock:
            stamps = self._stamps()
            tombstones = self._tombstones()
            custom = self._custom_words()
            enabled_norms = {normalized_filler_key(w) for w in (self._settings._get("filler_words") or [])}

            # Stamp legacy custom filler words created before sync existed.
            stamps_changed = False
            for w in custom:
                norm = normalized_filler_key(w)
                if norm and norm not in stamps:
                    stamps[norm] = utc_now()
                    stamps_changed = True
            if stamps_changed:
                self._settings.update_runtime({
                    FILLER_STAMPS_KEY: stamps,
                    FILLER_CUSTOM_KEY: custom,
                })

            custom_by_norm = {normalized_filler_key(w): w for w in custom}
            rows: list[dict] = []
            for norm, at in stamps.items():
                if at < stamp:
                    continue
                if norm in _PRESET_BY_NORM:
                    rows.append({
                        "word": _PRESET_BY_NORM[norm],
                        "enabled": norm in enabled_norms,
                        "deleted": False,
                        "updated_at": at,
                    })
                elif norm in custom_by_norm:
                    rows.append({
                        "word": custom_by_norm[norm],
                        "enabled": norm in enabled_norms,
                        "deleted": False,
                        "updated_at": at,
                    })
            for tomb in tombstones:
                if tomb["deleted_at"] >= stamp:
                    rows.append({
                        "word": tomb["word"],
                        "enabled": False,
                        "deleted": True,
                        "updated_at": tomb["deleted_at"],
                    })
            return rows

    def apply_remote(self, entries: Iterable[dict]) -> int:
        applied = 0
        with self._lock:
            stamps = self._stamps()
            tombstones = self._tombstones()
            custom = self._custom_words()
            enabled_list = [str(w) for w in (self._settings._get("filler_words") or [])]
            enabled_norms = {normalized_filler_key(w) for w in enabled_list}
            custom_by_norm = {normalized_filler_key(w): w for w in custom}
            changed_any = False

            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                raw_word = str(entry.get("word") or "")
                cleaned = " ".join(unicodedata.normalize("NFC", raw_word).split())
                norm = normalized_filler_key(cleaned)
                stamp = str(entry.get("updated_at") or "")
                if not norm or not stamp:
                    continue

                live_stamp = stamps.get(norm, "")
                tomb_stamp = next(
                    (t["deleted_at"] for t in tombstones if normalized_filler_key(t["word"]) == norm),
                    "",
                )
                local_stamp = max(live_stamp, tomb_stamp)
                if stamp < local_stamp:
                    continue

                deleted = bool(entry.get("deleted"))
                want_enabled = (not deleted) and bool(entry.get("enabled", True))

                if norm in _PRESET_BY_NORM:
                    was_enabled = norm in enabled_norms
                    if want_enabled != was_enabled:
                        if want_enabled:
                            enabled_norms.add(norm)
                        else:
                            enabled_norms.discard(norm)
                        applied += 1
                    stamps[norm] = stamp
                    tombstones = [t for t in tombstones if normalized_filler_key(t["word"]) != norm]
                    changed_any = True
                elif deleted:
                    if norm in custom_by_norm or norm in enabled_norms:
                        custom_by_norm.pop(norm, None)
                        enabled_norms.discard(norm)
                        applied += 1
                    stamps.pop(norm, None)
                    tombstones = [t for t in tombstones if normalized_filler_key(t["word"]) != norm]
                    tombstones.append({"word": cleaned, "deleted_at": stamp})
                    changed_any = True
                else:
                    if norm not in custom_by_norm:
                        custom_by_norm[norm] = cleaned
                        applied += 1
                    was_enabled = norm in enabled_norms
                    if want_enabled != was_enabled:
                        if want_enabled:
                            enabled_norms.add(norm)
                        else:
                            enabled_norms.discard(norm)
                        applied += 1
                    stamps[norm] = stamp
                    tombstones = [t for t in tombstones if normalized_filler_key(t["word"]) != norm]
                    changed_any = True

            if changed_any:
                ordered_custom = list(custom_by_norm.values())
                ordered_words = [w for w, _ in PRESET_FILLERS] + ordered_custom
                new_enabled = [w for w in ordered_words if normalized_filler_key(w) in enabled_norms]
                self._settings.update_runtime({
                    "filler_words": new_enabled,
                    FILLER_CUSTOM_KEY: ordered_custom,
                    FILLER_STAMPS_KEY: stamps,
                    FILLER_TOMBSTONES_KEY: tombstones[-1000:],
                })
        if applied:
            self._notify(CHANGE_SYNC)
        return applied


class PrefSync:
    """Syncs cross-platform device-independent preferences (`prefs`)."""

    def __init__(self, settings) -> None:
        self._settings = settings
        self._lock = threading.RLock()
        self._listeners: list[Callable[[str], None]] = []

    def add_listener(self, callback: Callable[[str], None]) -> None:
        self._listeners.append(callback)

    def _notify(self, kind: str) -> None:
        for cb in list(self._listeners):
            try:
                cb(kind)
            except Exception as exc:
                log.debug("PrefSync listener failed: %s", exc)

    def _stamps(self) -> dict[str, str]:
        raw = self._settings._get(PREF_STAMPS_KEY)
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items() if k in PREF_SPEC and v}

    def record_local_diff(self, before: dict, after: dict) -> bool:
        """Stamp every synced preference whose value changed between snapshots."""
        changed = False
        with self._lock:
            stamps = self._stamps()
            for wire_key, (local_key, kind) in PREF_SPEC.items():
                old_val = before.get(local_key)
                new_val = after.get(local_key)
                if kind == "bool":
                    if bool(old_val) == bool(new_val):
                        continue
                else:
                    if str(old_val or "") == str(new_val or ""):
                        continue
                stamps[wire_key] = _later(stamps.get(wire_key, EPOCH))
                changed = True
            if changed:
                self._settings.update_runtime({PREF_STAMPS_KEY: stamps})
        if changed:
            self._notify(CHANGE_LOCAL)
        return changed

    def _current_wire_value(self, wire_key: str) -> Optional[str]:
        spec = PREF_SPEC.get(wire_key)
        if spec is None:
            return None
        local_key, kind = spec
        raw = self._settings._get(local_key)
        if kind == "bool":
            return "true" if bool(raw) else "false"
        val = str(raw or "").strip()
        if wire_key == "dictation_language":
            return val or "auto"
        allowed = _VALID_STR_PREFS.get(wire_key)
        if allowed is not None and val not in allowed:
            return None
        return val

    def changes_since(self, stamp: str) -> list[dict]:
        rows: list[dict] = []
        with self._lock:
            for wire_key, at in self._stamps().items():
                if at < stamp:
                    continue
                val = self._current_wire_value(wire_key)
                if val is None:
                    continue
                rows.append({
                    "key": wire_key,
                    "value": val,
                    "deleted": False,
                    "updated_at": at,
                })
        return rows

    def apply_remote(self, entries: Iterable[dict]) -> int:
        applied = 0
        with self._lock:
            stamps = self._stamps()
            updates: dict = {}
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                wire_key = str(entry.get("key") or "")
                stamp = str(entry.get("updated_at") or "")
                if wire_key not in PREF_SPEC or not stamp:
                    continue
                if stamp < stamps.get(wire_key, ""):
                    continue
                local_key, kind = PREF_SPEC[wire_key]
                deleted = bool(entry.get("deleted"))
                if deleted:
                    stamps[wire_key] = stamp
                    continue
                raw_val = str(entry.get("value") or "").strip()
                if kind == "bool":
                    if raw_val not in ("true", "false"):
                        continue
                    parsed = raw_val == "true"
                    if bool(self._settings._get(local_key)) != parsed:
                        updates[local_key] = parsed
                        applied += 1
                else:
                    if wire_key == "dictation_language":
                        if not raw_val or (raw_val != "auto" and not (2 <= len(raw_val) <= 3 and raw_val.isalpha() and raw_val.islower())):
                            continue
                    else:
                        allowed = _VALID_STR_PREFS.get(wire_key)
                        if allowed is not None and raw_val not in allowed:
                            continue
                    if str(self._settings._get(local_key) or "") != raw_val:
                        updates[local_key] = raw_val
                        applied += 1
                stamps[wire_key] = stamp
            if updates or stamps != self._stamps():
                updates[PREF_STAMPS_KEY] = stamps
                self._settings.update_runtime(updates)
        if applied:
            self._notify(CHANGE_SYNC)
        return applied
