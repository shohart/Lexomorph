"""Filesystem layout for the Windows port.

The macOS build keeps everything under ``~/Library/Application Support/
SuperDictate`` with the FluidAudio model cache in a sibling directory.
Windows has no equivalent split, so one ``%LOCALAPPDATA%\\Lexomorph`` tree
holds settings, history and the ONNX model cache. Keeping the model inside
the same tree means an uninstall that spares user data also spares the
~600 MB download, matching the macOS uninstall.sh behaviour.

The app was called SuperDictate until 0.10.0 (and Dictation and D1CT before
that). The first launch under the new name *copies* the old tree here and
leaves the original alone: it is the way back if the new build has to be
rolled back. See :func:`migrate_legacy_directory`.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

# Not logging_setup's helper: that module imports this one, and the
# directories have to exist before logging can be configured at all.
log = logging.getLogger("superdictate.paths")

APP_NAME = "Lexomorph"
BUNDLE_ID = "com.lexomorph.windows"
# Where the app kept its data under its previous names, newest first.
LEGACY_APP_NAMES = ("SuperDictate", "Dictation", "D1CT")
ENV_PREFIX = "LEXOMORPH_"
# Read as a fallback for one release, so scripts that still set the old
# names keep working while their owners move over.
LEGACY_ENV_PREFIX = "SUPERDICTATE_"


def env(name: str) -> Optional[str]:
    """``LEXOMORPH_<name>``, else the pre-0.10 ``SUPERDICTATE_<name>``."""
    return os.environ.get(ENV_PREFIX + name) or os.environ.get(LEGACY_ENV_PREFIX + name)


def _local_app_data() -> Path:
    raw = os.environ.get("LOCALAPPDATA")
    if raw:
        return Path(raw)
    return Path.home() / "AppData" / "Local"


_HOME_OVERRIDE = (env("HOME")
                  or os.environ.get("DICTATION_HOME")
                  or os.environ.get("D1CT_HOME"))
BASE_DIR = Path(_HOME_OVERRIDE or (_local_app_data() / APP_NAME))
LEGACY_BASE_DIRS = tuple(_local_app_data() / name for name in LEGACY_APP_NAMES)

SETTINGS_FILE = BASE_DIR / "Settings.json"
HISTORY_FILE = BASE_DIR / "History.json"
USAGE_FILE = BASE_DIR / "Usage.json"
# Other devices' usage rows and this device's id (account sync).
USAGE_SYNC_FILE = BASE_DIR / "UsageSync.json"
CORRECTIONS_FILE = BASE_DIR / "Corrections.json"
PENDING_DICTATION_FILE = BASE_DIR / "PendingDictation.raw"
# Present only while the app is holding the system output muted. Left
# behind by a run that died mid-recording, and cleared by the next one
# after it unmutes.
MUTE_MARKER_FILE = BASE_DIR / "OutputMuted.flag"
LOG_DIR = BASE_DIR / "Logs"
LOG_FILE = LOG_DIR / "Lexomorph.log"
CRASH_FILE = LOG_DIR / "Crash.log"
MODELS_DIR = BASE_DIR / "Models"
CACHE_DIR = BASE_DIR / "Cache"
SINGLE_INSTANCE_MUTEX = "Global\\Lexomorph.SingleInstance"

#: Written into the new tree by the migration. ``status`` is "complete" or
#: "incomplete"; an incomplete one makes the next launch finish the copy.
MIGRATION_MARKER = ".migrated-from-superdictate.json"
# Not carried over: logs belong to the old build (and the old process may
# still hold them open), and the mute flag describes a state of that run.
_NOT_MIGRATED = frozenset({"Logs", "OutputMuted.flag", MIGRATION_MARKER})
_HARDLINK_ABOVE = 1 << 20


def _holds_user_data(directory: Path) -> bool:
    """Whether a tree is somebody's data rather than empty scaffolding.

    Existence is not the test. Every directory here is created on demand —
    an icon written to ``Cache`` is enough to bring the whole tree into
    being — so a check for the directory alone would call a settings file
    and 640 MB of weights "already migrated" and strand them under the old
    name forever.
    """
    return (directory / "Settings.json").exists()


def _marker_status(base: Path) -> Optional[str]:
    try:
        with open(base / MIGRATION_MARKER, "r", encoding="utf-8") as handle:
            return str(json.load(handle).get("status") or "complete")
    except FileNotFoundError:
        return None
    except (OSError, ValueError, AttributeError):
        return "complete"


def _write_marker(base: Path, source: Path, status: str) -> None:
    try:
        payload = {"status": status, "from": str(source), "version": 1,
                   "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        temp = base / (MIGRATION_MARKER + ".tmp")
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temp, base / MIGRATION_MARKER)
    except OSError as exc:
        log.warning("Could not write the migration marker: %s", exc)


def _copy_file(source: Path, target: Path, allow_link: bool) -> None:
    """Copy, or hard-link a big file where the file system allows it.

    A link shares the bytes with the original, so it is used only for the
    model weights: nothing rewrites those in place (a download lands in a
    temporary name and is moved over), and copying 640 MB twice for a
    rename is a poor welcome.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if allow_link and source.stat().st_size >= _HARDLINK_ABOVE:
        try:
            os.link(source, target)
            return
        except OSError:
            pass  # another volume, or a file system without links
    temp = target.with_name(target.name + ".migrating")
    shutil.copy2(source, temp)
    os.replace(temp, target)


def _copy_tree(source: Path, target: Path, errors: list[str], *,
               top: bool = True, allow_link: bool = False) -> bool:
    """Add what is missing from ``target``; never overwrite, never delete."""
    copied = False
    try:
        entries = sorted(source.iterdir(), key=lambda path: (path.name == "Settings.json", path.name))
    except OSError as exc:
        errors.append(f"{source}: {exc}")
        return False
    for entry in entries:
        if top and entry.name in _NOT_MIGRATED:
            continue
        if entry.name.endswith((".tmp", ".migrating", ".part")):
            continue
        destination = target / entry.name
        try:
            if entry.is_dir() and not entry.is_symlink():
                link = allow_link or (top and entry.name == "Models")
                copied |= _copy_tree(entry, destination, errors, top=False, allow_link=link)
            elif not destination.exists():
                _copy_file(entry, destination, allow_link)
                copied = True
        except OSError as exc:
            errors.append(f"{entry}: {exc}")
    return copied


def migrate_legacy_directory(base: Optional[Path] = None,
                             legacy_dirs: Optional[tuple] = None) -> bool:
    """Copy the data tree of a previous app name into place.

    Returns True if the copy ran (complete or not). Non-destructive: the old
    tree is only read, so rolling back to the old build loses nothing, and
    nothing in the new tree is overwritten. Idempotent: a "complete" marker
    ends it, and a tree that already has its own ``Settings.json`` and no
    marker belongs to somebody who started fresh, so old data is not pushed
    back at them. A failure is logged, never raised; an incomplete run is
    resumed by the next launch. The newest previous name wins.
    """
    base = BASE_DIR if base is None else Path(base)
    legacy_dirs = LEGACY_BASE_DIRS if legacy_dirs is None else legacy_dirs
    try:
        status = _marker_status(base)
        if status == "complete":
            return False
        if status is None and _holds_user_data(base):
            return False
        for legacy in legacy_dirs:
            legacy = Path(legacy)
            if not _holds_user_data(legacy):
                continue
            try:
                if base.resolve() == legacy.resolve():
                    continue
            except OSError:
                continue
            base.mkdir(parents=True, exist_ok=True)
            errors: list[str] = []
            _copy_tree(legacy, base, errors)
            for problem in errors:
                log.warning("Migration from %s: could not copy %s", legacy, problem)
            _write_marker(base, legacy, "incomplete" if errors else "complete")
            log.info("Copied the data of %s to %s (%s)", legacy.name, base,
                     "incomplete, will resume" if errors else "complete")
            return True
    except Exception as exc:  # a migration never blocks the start
        log.warning("Data migration failed: %s", exc)
    return False


def ensure_directories() -> None:
    if migrate_legacy_directory():
        _migrate_sync_token()
    for directory in (BASE_DIR, LOG_DIR, MODELS_DIR, CACHE_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def resource_path(*parts: str) -> Path:
    """Resolve a bundled resource both in-tree and inside a PyInstaller bundle."""
    import sys

    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root.joinpath(*parts)


def _migrate_sync_token() -> None:
    """Re-protect a copied sync token under the new DPAPI entropy.

    The token is a DPAPI blob bound to the old app's entropy string, so a
    plain copy would not decrypt under the new one. Never raises.
    """
    try:
        from .vocabulary_sync import DpapiTokenStore

        DpapiTokenStore().migrate_legacy()
    except Exception as exc:
        log.warning("Could not re-protect the sync token: %s", exc)
