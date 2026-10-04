"""Single owner of filter_state.json: location, migration, cache, and saving.

Every module that persists something (state.py's engine modes / settings /
history, stats.py's counters, bookmarks, search profiles, settings imports)
goes through this interface and never touches the file, cache, or lock.

Changes are *operations*, not snapshots. ``update(op)`` applies a mutation to
the in-memory view and remembers it. Saving takes an inter-process lock,
re-reads the file, replays the remembered operations onto that fresh copy,
and atomically replaces it. Another Torrent Finder window's newer changes are
therefore never overwritten by a stale in-memory copy (see ADR-0019).

- ``read()`` — the current view; picks up changes another window saved.
- ``update(op)`` — best-effort change (stats, history, update checks), saved
  by ``flush()`` at exit.
- ``commit(op)`` — explicit user action (Save, Clear, bookmark, import): saved
  immediately. On failure ``ValueError`` / ``SaveError`` is raised and the view
  is unchanged, so the caller can keep its draft and offer a retry.

If the file exists but cannot be read at startup (after short retries for
transient locks), the store is *unavailable*: the session runs on defaults,
nothing is written, and ``problem()`` describes it until ``retry_load()`` or
``set_aside_unreadable()`` recovers.
"""

import atexit
import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime

from torrent_finder.constants import legacy_data_paths, machine_state_path

STATE_PATH = machine_state_path("filter_state.json")
LEGACY_STATE_PATHS = legacy_data_paths("filter_state.json")

_cache: dict | None = None
_pending: list = []        # operations applied to _cache but not yet on disk
_signature = None          # identity of the file version _cache is based on
_problem = None            # StorageProblem while saved settings are unreadable
_atexit_registered: bool = False
_mutex = threading.RLock()

LOCK_TIMEOUT = 5.0         # explicit saves wait this long for another window
_FLUSH_LOCK_TIMEOUT = 3.0  # exit never hangs longer than this
# Windows antivirus/sync tools and another window's reader briefly hold files open.
_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)


class SaveError(OSError):
    """An explicit save did not reach the disk; saved data was not changed."""


class StorageProblem:
    """Why saved settings could not be read; ``damaged`` means invalid content."""

    __slots__ = ("path", "reason", "damaged")

    def __init__(self, path: str, reason: str, damaged: bool) -> None:
        self.path, self.reason, self.damaged = path, reason, damaged

    def message(self) -> str:
        return (f"Saved settings could not be read ({self.reason}): {self.path}. "
                "The file was left untouched, and changes are not saved until it can be read.")


class _Unreadable(Exception):
    def __init__(self, reason: str, damaged: bool) -> None:
        super().__init__(reason)
        self.reason, self.damaged = reason, damaged


def _read_document(path: str, *, patient: bool = False) -> dict | None:
    """The JSON object at *path*, or None when missing. Raises ``_Unreadable``.

    *patient* retries OS errors briefly; invalid content is never retried.
    """
    for delay in (*(_RETRY_DELAYS if patient else ()), None):
        try:
            with open(path, "rb") as stream:
                raw = stream.read()
            break
        except FileNotFoundError:
            return None
        except OSError as error:
            if delay is None:
                raise _Unreadable(error.strerror or str(error), damaged=False) from error
            time.sleep(delay)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise _Unreadable("the file is not valid settings data", damaged=True) from error
    if not isinstance(data, dict):
        raise _Unreadable("the file is not valid settings data", damaged=True)
    return data


def _read_json(path: str) -> dict | None:
    """Best-effort read for legacy copies: None when missing or unreadable."""
    try:
        return _read_document(path)
    except _Unreadable:
        return None


def _file_signature(path: str):
    try:
        status = os.stat(path)
    except OSError:
        return None
    return status.st_mtime_ns, status.st_size, status.st_ino


def _history_identity(entry: dict) -> tuple:
    if entry.get("kind", "keyword") == "creator":
        return (
            "creator",
            entry.get("provider", ""),
            entry.get("facet", ""),
            (entry.get("name", "") or "").lower(),
        )
    return (
        "keyword",
        entry.get("provider", ""),
        (entry.get("query", "") or "").lower(),
        tuple(q.casefold() for q in entry.get("queries", []) if isinstance(q, str)),
    )


def _merge_history(copies: list[tuple[float, dict]]) -> list[dict]:
    indexed = []
    for _, data in copies:
        for entry in data.get("history", []):
            if isinstance(entry, dict):
                indexed.append((len(indexed), entry))

    indexed.sort(
        key=lambda pair: (str(pair[1].get("timestamp", "")), pair[0]),
        reverse=True,
    )
    merged = []
    seen = set()
    for _, entry in indexed:
        identity = _history_identity(entry)
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(entry)
    return merged[:50]


def _merge_stat_value(current, incoming, key: str):
    if (
        key == "first_use"
        and isinstance(current, str)
        and isinstance(incoming, str)
    ):
        return min(current, incoming)
    if isinstance(current, dict) and isinstance(incoming, dict):
        merged = dict(current)
        for child_key, value in incoming.items():
            if child_key in merged:
                merged[child_key] = _merge_stat_value(
                    merged[child_key], value, child_key
                )
            else:
                merged[child_key] = value
        return merged
    if (
        isinstance(current, (int, float))
        and not isinstance(current, bool)
        and isinstance(incoming, (int, float))
        and not isinstance(incoming, bool)
    ):
        return max(current, incoming)
    return incoming


def _merge_state_copies(copies: list[tuple[float, dict]]) -> dict:
    """Consolidate diverged state without double-counting cumulative stats."""
    ordered = sorted(copies, key=lambda copy: copy[0])
    merged = {}
    has_history = False
    stats = None
    for _, data in ordered:
        merged.update(data)
        if isinstance(data.get("history"), list):
            has_history = True
        candidate_stats = data.get("stats")
        if isinstance(candidate_stats, dict):
            stats = (
                candidate_stats
                if stats is None
                else _merge_stat_value(stats, candidate_stats, "stats")
            )

    if has_history:
        merged["history"] = _merge_history(ordered)
    if stats is not None:
        merged["stats"] = stats
    return merged


def _initial_load(target_path: str, legacy_paths: list[str]):
    """Return ``(data, problem, unsaved_migration)`` for the first read."""
    try:
        current = _read_document(target_path, patient=True)
    except _Unreadable as error:
        # Preserve an unreadable authoritative file for recovery.
        return {}, StorageProblem(target_path, error.reason, error.damaged), None
    if current is not None:
        return current, None, None

    copies = []
    seen = set()
    for path in legacy_paths:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen or key == os.path.normcase(os.path.abspath(target_path)):
            continue
        seen.add(key)
        data = _read_json(path)
        if data is not None:
            try:
                modified = os.path.getmtime(path)
            except OSError:
                modified = 0.0
            copies.append((modified, data))

    if not copies:
        return {}, None, None

    merged = _merge_state_copies(copies)
    try:
        atomic_json(target_path, merged)
    except OSError:
        return merged, None, merged
    return merged, None, None


def _load_initial_state(target_path: str, legacy_paths: list[str]) -> dict:
    return _initial_load(target_path, legacy_paths)[0]


def _seed(document: dict):
    """Operation that writes a migration whose first save failed, if still absent."""
    def apply(data):
        if not data:
            data.update(deepcopy(document))
    return apply


def _replace_document(document: dict):
    def apply(data):
        data.clear()
        data.update(deepcopy(document))
    return apply


def _ensure_loaded() -> None:
    global _cache, _problem, _signature, _atexit_registered
    if _cache is not None:
        return
    signature = _file_signature(STATE_PATH)  # before reading: a racing save triggers a refresh
    data, problem, unsaved = _initial_load(STATE_PATH, LEGACY_STATE_PATHS)
    _cache, _problem = data, problem
    _signature = None if problem else signature
    if unsaved is not None:
        _pending.append(_seed(unsaved))
    if not _atexit_registered:
        atexit.register(flush)
        _atexit_registered = True


def _refresh_if_changed() -> None:
    """Adopt a version another window saved, keeping this session's pending changes."""
    global _cache, _signature
    if _problem is not None:
        return
    signature = _file_signature(STATE_PATH)
    if signature is None or signature == _signature:
        return
    try:
        fresh = _read_document(STATE_PATH)
        if fresh is None:
            return
        for op in _pending:
            op(fresh)
    except Exception:
        return  # keep the current view; a later read tries again
    _cache, _signature = fresh, signature


def section(data: dict, key: str) -> dict:
    """The dict stored at ``data[key]``, created (or replaced if malformed)."""
    value = data.get(key)
    if not isinstance(value, dict):
        value = data[key] = {}
    return value


def read() -> dict:
    """Return the current state view, loading from disk on first call.

    Treat it as read-only: change state with ``update`` or ``commit``.
    """
    with _mutex:
        _ensure_loaded()
        _refresh_if_changed()
        return _cache


def update(op) -> None:
    """Apply a best-effort change now; ``flush()`` replays it onto the saved file."""
    with _mutex:
        read()
        op(_cache)
        _pending.append(op)


def problem() -> StorageProblem | None:
    """Describe unreadable saved settings, or None when storage is healthy."""
    with _mutex:
        _ensure_loaded()
        return _problem


if os.name == "nt":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def _file_lock(path: str, timeout: float):
    """Exclusive inter-process lock covering one read-modify-write of *path*."""
    lock_path = path + ".lock"
    os.makedirs(os.path.dirname(os.path.abspath(lock_path)), exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + timeout
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                raise SaveError("Another Torrent Finder window is saving settings. Try again in a moment.")
            time.sleep(0.05)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


def _replace(source: str, target: str) -> None:
    for delay in _RETRY_DELAYS:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            time.sleep(delay)  # Windows: a reader briefly holds the target open
    os.replace(source, target)


def atomic_json(path, data) -> None:
    """Replace one complete JSON document; failed writes leave its old bytes intact."""
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".torrent-settings-", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        _replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _save(extra_op, timeout: float):
    """Fresh file + pending operations (+ *extra_op*) → disk, under the lock."""
    with _file_lock(STATE_PATH, timeout):
        try:
            document = _read_document(STATE_PATH, patient=True) or {}
        except _Unreadable as error:
            raise ValueError("Existing settings cannot be read; the file was preserved.") from error
        for op in _pending:
            op(document)
        if extra_op is not None:
            extra_op(document)
        atomic_json(STATE_PATH, document)
        return document, _file_signature(STATE_PATH)


def commit(change) -> None:
    """Explicitly save *change* now: an operation, or a dict replacing the document.

    Pending best-effort changes are saved with it. Raises ``ValueError`` when
    saved settings are unreadable (or the operation rejects them) and
    ``SaveError`` when writing fails; the view is unchanged in both cases.
    """
    global _cache, _signature
    op = change if callable(change) else _replace_document(change)
    with _mutex:
        _ensure_loaded()
        if _problem is not None:
            raise ValueError(_problem.message())
        try:
            document, signature = _save(op, LOCK_TIMEOUT)
        except SaveError:
            raise
        except OSError as error:
            raise SaveError(f"Couldn't save settings ({error.strerror or error}). Nothing was changed.") from error
        _cache, _signature = document, signature
        _pending.clear()


def flush() -> None:
    """Best-effort save of pending changes; runs at exit and never raises."""
    global _cache, _signature
    with _mutex:
        if not _pending or _cache is None or _problem is not None:
            return
        try:
            document, signature = _save(None, _FLUSH_LOCK_TIMEOUT)
        except Exception:
            return
        _cache, _signature = document, signature
        _pending.clear()


def retry_load() -> bool:
    """Re-read unreadable saved settings; True once storage is healthy."""
    global _cache, _signature, _problem
    with _mutex:
        _ensure_loaded()
        if _problem is None:
            return True
        signature = _file_signature(STATE_PATH)
        try:
            data = _read_document(STATE_PATH, patient=True) or {}
        except _Unreadable as error:
            _problem = StorageProblem(STATE_PATH, error.reason, error.damaged)
            return False
        for op in _pending:
            op(data)
        _cache, _signature, _problem = data, signature, None
        return True


def set_aside_unreadable() -> str:
    """Rename unreadable saved settings aside and start fresh; return the new path."""
    global _cache, _signature, _problem
    with _mutex:
        _ensure_loaded()
        if _problem is None:
            return ""
        root, extension = os.path.splitext(STATE_PATH)
        aside = f"{root}.unreadable-{datetime.now():%Y%m%d-%H%M%S}{extension}"
        with _file_lock(STATE_PATH, LOCK_TIMEOUT):
            os.rename(STATE_PATH, aside)
        data = {}
        for op in _pending:
            op(data)
        _cache, _signature, _problem = data, None, None
        return aside
