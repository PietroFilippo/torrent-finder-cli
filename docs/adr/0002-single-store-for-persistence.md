# ADR-0002: One store owns filter_state.json

Status: accepted (2026-07-04)

## Context

All persistent app state (engine toggles, presets, settings, history, stats)
lives in one JSON file, `filter_state.json`, behind an in-memory cache with a
dirty flag, flushed at process exit. That cache/dirty/flush lifecycle lived in
`state.py` as private helpers, and `stats.py` imported `_read_state` /
`_write_state` / `_flush` directly — two modules moving in lockstep with
nobody owning the file. Testing stats meant touching the real state path.

## Decision

`store.py` is the single owner of the file: `read()` (loads on first call,
registers atexit flush), `write()` (cache + dirty, no disk hit), `flush()`
(persist if dirty). `state.py` and `stats.py` are callers of that public trio
and never touch the file, the cache, or the dirty flag.

Flush policy is unchanged: batched to process exit, except destructive or
explicitly-confirmed user actions (`save_state`, `clear_history`,
`reset_stats`) which flush immediately so they survive a hard kill.

## Consequences

- Persistence bugs have one home; the write-batching policy is stated once.
- Headless tests: point `store.STATE_PATH` at a temp file before first
  `read()` and everything above it runs without the real file.
- Anything new that wants persistence (e.g. a future credentials move) calls
  the store instead of growing its own file handling.
- One file/one cache stays a deliberate constraint — if the file ever needs
  splitting, the store is the only place that changes.
