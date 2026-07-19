# ADR-0010: Knaben and explicit engine modes

Status: accepted (2026-07-18)

## Context

The APIBay resilience work introduced emergency engines that were internally
different from explicitly disabled engines. The filter menu still rendered
both as unchecked, so an engine could make a network request while appearing
Off. That is not an honest user control.

YTS has intermittent API hosts, while SolidTorrents often adds poorly scoped
rows. A useful fallback should cover several trackers, accept category
constraints, return stable info hashes, and not require a credential.

## Decision

Every `SearchEngine` exposes an explicit mode:

- **On** runs in the normal concurrent fan-out.
- **Auto** runs only when all On engines return zero merged raw rows, before
  local filters. If no engines are On, eligible Auto engines still run.
- **Off** is never contacted.

Only engines declared fallback-capable offer Auto. The filter selector renders
the named modes and cycles them with Enter or Space. `state.py` persists
`engine_modes` while retaining the former boolean and explicit-disable fields
for backward compatibility. Valid explicit modes take precedence; older state
continues through the conservative legacy migration.

Knaben is added as the default Auto engine for Movies & Series, Games, Desktop
Software, Mobile, Anime, Manga, and Books. Each provider owns its Knaben
category mapping. One search:

- sends a single POST to the documented API;
- uses exact title-field matching and seeder-descending ordering;
- enables Knaben's unsafe and XXX hiding controls;
- requests at most 50 rows;
- accepts only 40- or 64-character hexadecimal info hashes; and
- preserves the originating tracker, category, last-seen time, and risk score
  as result provenance.

Knaben stays `source="Knaben"` and therefore uses the ordinary magnet-direct
acquisition path. YTS and SolidTorrents remain selectable but default to Off,
not Auto.

## Consequences

- The UI accurately describes whether an engine can make a request.
- One category-scoped meta-index replaces multiple noisy emergency scrapers
  without removing those manual options.
- Knaben can still be rate-limited, malformed, or unavailable; the adapter
  fails closed and does not retry-amplify.
- Knaben's safety flag and risk score reduce exposure but cannot prove a
  torrent is safe. Users still need to inspect releases, especially software.
- A new engine absent from old saved state starts at its code-defined Auto
  default, while existing user choices remain deterministic.
