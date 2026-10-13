# Development

## Setup

Clone and install in editable mode as the [README](../README.md#install)
shows. Run the app with `torrent-finder`, `python -m torrent_finder` or `torrent.bat`
(Windows). An editable install keeps pointing at your clone, so `git pull`
updates it.

Start with [CONTEXT.md](../CONTEXT.md) for the domain vocabulary and a map of
the code, and [the ADRs](adr/) for decisions with history.

## Tests

The suite is headless and never touches public network services or your real
settings (`tests/isolation.py` redirects saved data to a temporary folder; when
aria2c is installed, one test downloads from a local HTTP server):

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

## Translating

Screens write English and ask for it in the interface language when they
draw ([ADR-0028](adr/0028-interface-languages.md)):

```python
from torrent_finder.i18n import N_, t, tn

HELP = N_("Shows the painting behind the app.")      # module level: marked, not translated

def footer(count, name):
    return "\n".join([
        t(HELP),                                      # translated when drawn
        t("Saved {name}", name=name),                 # named placeholders only
        tn("{n} result", "{n} results", count),
        t("Off", ctx="engine mode"),                  # one English word, two meanings
        t("Age", ctx="column"),  # i18n: budget=5
    ])
```

Never call `t()` at import time (module level, class body, default values):
the check fails. Comparisons and saved values keep English or a key.

Converting a module:

1. `python scripts/i18n.py bare torrent_finder/ui/x.py` lists the literals
   that read as UI text. Wrap them in `t()`/`tn()`, or `N_()` where they are
   defined at import time; mark a line that stays English `# i18n: ignore`.
2. Add a `# i18n: converted` line to the module: from then on a bare UI
   literal in it fails the tests.
3. `python scripts/i18n.py todo pt-BR --files torrent_finder/ui/x.py` lists
   the new messages with the code around them, any width budget, the glossary
   terms they contain and a JSON skeleton. Translate into
   `torrent_finder/assets/locales/pt-BR/ui-x.json` (one file per module, so
   parallel work never edits the same file; shared words in `common.json`),
   following [the style guide](i18n/pt-BR.md).
4. `python scripts/i18n.py check pt-BR` must say "No problems"; so must the
   tests, which run the same checks. `python scripts/i18n.py stats` counts
   messages and translations per module.

To see it, run with `--lang pt-BR` (or `TORRENT_FINDER_LANG=pt-BR`), or
`--lang qps`: the pseudo-locale brackets, accents and pads every converted
message, so English left on screen is unconverted and a frame that overflows
needs room for longer text.

Adding a language: add its code and its own name to `i18n.LANGUAGES`
(`"es": "Español"`), create `torrent_finder/assets/locales/<code>/`, write
`docs/i18n/<code>.md` and `<code>.glossary.json`, and give `i18n._plural` its
plural rule if "one for 1, other otherwise" does not fit. `check` then
reports every message the language lacks.

## Releasing

See [releasing.md](releasing.md).
