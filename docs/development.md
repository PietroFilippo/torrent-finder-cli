# Development

## Setup

Clone and install in editable mode as the [README](../README.md#install)
shows. Run the app with `torrent-finder`, `python -m torrent_finder` or `torrent.bat`
(Windows). An editable install keeps pointing at your clone, so `git pull`
updates it.

Start with [CONTEXT.md](../CONTEXT.md) for the domain vocabulary and a map of
the code, and [the ADRs](adr/) for decisions with history.

## Tests

The suite is headless and never touches the network or your real settings
(`tests/isolation.py` redirects saved data to a temporary folder):

```bash
python -m unittest discover -s tests
python -m pytest
```

The release workflow runs unittest on Linux with the newest versions of the
unpinned dependencies, so run both runners locally; before a release, also try
the newest Rich.

## Live source checks

These scripts contact real sources and are never run by the tests or CI.

**APIBay** can answer HTTP 200 with a false "No results returned", so its live
behaviour is checked separately. The harness runs known movie, book and game
queries one after another and reports success rate, cache use, request
amplification and latency:

```bash
python scripts/stress_apibay.py --rounds 3
```

A count ending in `*` came from the last-known-good cache (`apibay_cache.json`,
at most 128 queries); live searches always run first.

**Knaben** has its own matrix:

```bash
python scripts/stress_knaben.py --rounds 1
```

Its default delay is deliberate: it is a smoke test, not a load generator.

Both accept `--delay SECONDS` between searches and `--strict`, which exits
nonzero when any query returns no usable rows.

The provider audit (`python -m scripts.provider_audit --run`) is an opt-in,
resumable live audit; [REPRODUCING.md](audits/2026-10-03/REPRODUCING.md)
explains how to rebuild the October 2026 audit's results offline from its
saved evidence.

## UI checks

- `python scripts/ui_snapshots.py capture NAME` records every screen as text at
  several sizes; `compare A B` lists what changed, `check NAME` reports overflow,
  and `themes` covers every theme.
- `python -m torrent_finder --preview-update [failure]` plays the update screen
  in the terminal without installing anything. `python -m scripts.preview_update`
  exports a browser replay, with success, failure and compact-terminal controls,
  to `dist/update-preview/index.html`. Both use the real renderer and change
  nothing.
- `python scripts/build_paintings.py` rebuilds the Athanor paintings from
  Wikimedia Commons (needs Pillow and the network).

## Releasing

See [releasing.md](releasing.md).
