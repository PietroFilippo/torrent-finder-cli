# Architecture Roadmap

This is the agreed sequence for the result/acquisition cleanup.

## Current Sequence

1. Done: `CONTEXT.md` and ADR trail.
2. Done: single `store.py` owner for `filter_state.json`.
3. Done: focused characterization tests while introducing `SearchResult`.
4. Done: implement a typed `SearchResult` contract.
5. Done: acquisition seam — per-source adapters in `acquisition.py` (ADR-0003).
6. Done: derive CLI/provider choices from the provider registry (ADR-0004).
7. Done: extract a typed credentials registry (ADR-0005).

## Notes

- `SearchResult` should make producer/parser behavior assertable without relying
  on drift-prone dict defaults.
- The acquisition interface should cover the existing four styles:
  magnet-direct, magnet-lazy-resolve, torrent-file-handoff, and direct-download.
- Tests should stay mostly headless and avoid network by mocking site clients.
