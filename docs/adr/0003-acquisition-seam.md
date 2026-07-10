# ADR-0003: Acquisition is a per-source adapter seam

Status: accepted (2026-07-09)

## Context

How a picked result becomes files on disk was decided by re-testing
`result["source"]` at ~11 independent sites in `main.py` (`_magnet_for`,
`_batch_handoff`, `_batch_flow`, `browse_results`, plus the per-site
`_online_fix_pick` / `_madokami_pick` handlers). Adding one non-standard
source (done twice: Online-Fix, then Madokami) meant ~9 edit points across
four files, and none of the branching was testable without a terminal —
everything ran under readchar.

## Decision

`acquisition.py` owns the seam. Four adapters — `MagnetDirect`,
`MagnetLazyResolve` (RuTracker, FitGirl), `OnlineFixAcquisition`
(torrent-file-handoff), `MadokamiAcquisition` (direct-download) — implement
one interface:

- `magnet(result)` — magnet URI or None; silent (callers own their status UI).
- `pick(result)` — interactive single pick, returning a `PickOutcome`
  (`menu` with a magnet, `next`, or `back`).
- `batch_item(result, ...)` — one batch-handoff item, returning a
  `BatchItemOutcome` (`ok`, `saved_direct`, `manual_url`, `password`) that the
  batch loop aggregates.

The registry (`for_result`) is keyed by result `source`, **not by provider**:
a provider merges engines with different acquisition styles into one results
table (Games mixes Apibay, SolidTorrents, Online-Fix, and FitGirl rows), so
the provider is the wrong granularity. Unregistered sources default to
magnet-direct.

## Consequences

- Single pick, batch handoff, copy-magnets, and batch-aria2 all drive the
  same interface; `main.py` carries no per-source branching.
- A new non-standard source is one adapter plus one `_BY_SOURCE` line, instead
  of edits at every consumer.
- The seam is headless-testable with mocked site calls
  (`tests/test_acquisition_seam.py`); the magnet contract is additionally
  pinned by `tests/test_acquisition_characterization.py`.
- Adapters carry their own Rich UI for the interactive `pick`, so
  `acquisition.py` is not UI-free — the split is per-source locality, not
  UI/logic purity.
- `main._magnet_for` survives as a thin delegate for the characterization
  tests.
