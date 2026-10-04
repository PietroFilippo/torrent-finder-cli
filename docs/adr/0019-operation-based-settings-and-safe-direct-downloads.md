# ADR-0019: Operation-based settings saves and safe direct downloads

Status: accepted (2026-10-03). Amends the write/flush lifecycle of ADR-0002.

## Context

`store.py` cached the whole `filter_state.json` and wrote that snapshot back at
exit. Three failures followed from the snapshot model. A file that could not be
read at startup (briefly locked by antivirus, a sync tool or another window)
became `{}` in memory; once readable again, the exit save replaced settings,
history, profiles and bookmarks with that session's stats. Two open windows
overwrote each other: the window closed last erased bookmarks the other had
saved. Explicit Save, Clear history and Reset stats went through the
fail-silent exit flush, so a failed write looked successful until restart.

Separately, Madokami and Libgen wrote straight to the final filename. A
re-download truncated the existing complete file, and Esc or a network error
then deleted it as "partial" output; Ctrl+C left partial bytes under the final
name.

## Decision

Changes are operations, not snapshots. `store.update(op)` applies a change to
the in-memory view and remembers it; saving takes an inter-process lock
(`filter_state.json.lock`, released by the OS if the process dies), re-reads
the file, replays the remembered operations onto it and atomically replaces
it. `store.read()` adopts versions another window saved, with this session's
pending operations reapplied. Statistics are increments, history additions are
deduplicating inserts, and bookmark edits apply to the saved collection, so
concurrent windows combine their changes. A deletion made in one window is
never undone by another, because nothing replays a stale copy of the data. When
two windows explicitly save the same item, the later save wins.

Explicit user actions (Save profiles, filter Confirm, Clear history, Reset stats,
bookmarks, settings import) call `store.commit(op)`: the change is saved
immediately, and the view changes only after it reaches the disk. Failure raises
`ValueError` (unreadable settings) or `store.SaveError` (write failed or the
lock is busy for five seconds), and the UI says so while keeping the draft for a
retry. Session-scoped changes (stats, history additions, update checks, ordinary
settings) remain best-effort and never raise. They are saved in the background
about a second after the first unsaved change, and again at exit. Closing the
console window skips exit handlers, so an exit-only save would lose the
session's searches.

A file that exists but cannot be read after short retries makes the store
*unavailable*. The session runs on defaults, nothing is written, and explicit
saves report the problem. At startup the user can try again, keep a renamed copy
of damaged content and start fresh, or continue without saving. A missing file
is still a new install.

Direct downloads share `direct_download.save_response`. It streams to a
temporary `.part` sibling and promotes it only when complete. Esc, failures and
Ctrl+C remove only that temporary file. Promotion never replaces an existing
file: a taken name becomes `Name (1).ext`, because two different Libgen books can
share a filename. The completion screen shows the name actually saved.

## Consequences

- Operations must be deterministic and tolerate the shapes they may meet on
  disk; values such as timestamps and IDs are computed before the operation.
  `store.section()` creates or repairs a dict subtree. A pending operation that
  still fails on what another window or a hand edit wrote is dropped rather than
  blocking every later save; an explicit save that fails this way raises
  `ValueError`. The first migration takes the file lock and adopts a file
  another window created meanwhile. Search profiles replay a window's own
  changes by profile ID instead of replacing the collection.
- No single-instance restriction or database is needed for concurrent windows.
- Tests import `tests/isolation.py`, which redirects saved settings, credentials
  and the Apibay cache for the whole run. `isolate_store(case)` gives a test its
  own fresh file and store.
- Re-downloading a volume or book keeps the earlier copy; the user removes
  duplicates they don't want.
