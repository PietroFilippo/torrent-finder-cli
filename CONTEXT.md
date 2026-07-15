# CONTEXT.md — domain model

The vocabulary this codebase is written in. Code comments point here
(`torrent_session.py`, `providers/__init__.py`); decisions with history live in
[docs/adr/](docs/adr/).

## Provider

A content vertical the user picks on the first screen: what they're looking
for, not where it comes from. One instance of a `BaseProvider` subclass
(`providers/*_provider.py`), registered once in the flat `PROVIDERS` list
(`providers/__init__.py`).

- **`slug` is the identity key** — immutable, lowercase (`movies`, `games`,
  `online-fix`, `fitgirl`, `software`, `mobile`, `rutracker`, `anime`, `manga`,
  `madokami`). Persistence (history, stats, settings), the `-t` CLI flag, and
  all lookups resolve against it. See [ADR-0001](docs/adr/0001-provider-slug-identity.md).
- **`name` is a display label** — free to change (`"Movies & Series"`,
  `"General"`), never used for identity. Duplicate names across providers are
  fine (both game and manga "General").
- **CLI choices come from the registry** — every Provider's canonical `slug`
  is accepted by `-t`; optional `cli_aliases` preserve older spellings
  (`movie`, `game`). The `--by` choices are the unique union of registered
  Providers' `creator_facets`. See
  [ADR-0004](docs/adr/0004-provider-registry-drives-cli-choices.md).
- A provider declares capabilities as class attributes (`supports_subtitles`,
  `supports_episode_picker`, `supports_streaming`), default filters, presets,
  and optional creator-search facets.

**ProviderGroup** is display-only nesting on the Select Provider screen
(Games, Software, Manga umbrellas). It changes menu shape, never identity —
group children stay in flat `PROVIDERS` with their own slugs.

## Engine

A search backend inside a provider (`SearchEngine` in `providers/base.py`):
Apibay, SolidTorrents, Nyaa (per-category), or a site-specific scraper. A
provider fans a query out to all enabled engines concurrently, merges on
`info_hash`, filters, and sorts by seeders. Engines are user-toggleable per
provider; the toggle persists under the provider's slug.

## Result

What a search returns: a `SearchResult` (`search_result.py`) per row. Common
fields are explicit: `name`, `info_hash`, `seeders`, `leechers`, `size`
(bytes), `source`, `page_url`, and optional `from_work` provenance for
multi-title / creator searches. `seeders`, `leechers`, and `size` are normalized
to integers at construction.

Source-specific acquisition identifiers live in `SearchResult.handle`:
`rt_topic_id` (RuTracker), `fg_post_url` (FitGirl), `of_post_url` (Online-Fix),
`mdk_path` (Madokami). During migration, `SearchResult` still behaves like a
mapping, so legacy reads such as `result.get("rt_topic_id")` continue to work.

## Acquisition

How a picked result becomes files on disk. Four styles exist, each an adapter
in `acquisition.py` behind one interface
(see [ADR-0003](docs/adr/0003-acquisition-seam.md)):

1. **magnet-direct** — result carries a real `info_hash`; build a magnet
   (Apibay, SolidTorrents, Nyaa, YTS — and any unregistered source).
2. **magnet-lazy-resolve** — hash lives on the topic/post page, fetched on
   demand (`rutracker.resolve_info_hash`, `fitgirl.resolve_info_hash`).
3. **torrent-file-handoff** — no public magnet; fetch the `.torrent` and open
   it in the system client (Online-Fix; file host is referer-gated).
4. **direct-download** — no torrent at all; stream files straight to the
   download folder (Madokami, login required).

The adapter is chosen by `result.source` via `acquisition.for_result()` —
keyed per source, not per provider, because one provider merges engines with
different styles (Games mixes Apibay, Online-Fix, and FitGirl rows). Every
consumer path drives the same interface: `magnet()` (silent; copy-magnets and
batch-aria2), `pick()` (interactive single pick), `batch_item()` (batch
handoff). A new non-standard source is one adapter plus one registry line.

## Session

`TorrentSession` (`torrent_session.py`): post-pick state owner, constructed
once per torrent the user picks, alive for the download-method menu loop. It
caches the file list, tracks selected files (episode picker) and subtitle
choice. **Rule: stream adapters consume the session directly; download
adapters take `session.magnet` + `session.download_indexes` projections and
stay session-unaware.**

## Filters & Presets

`FilterConfig` (`filters.py`) structures result filtering (size/seeders/
keywords). Applied in order: provider defaults → active presets → CLI flags.
A `FilterPreset` is a named config the user toggles per provider; active
presets persist under the provider's slug.

## Resolver (creator search)

The resolver layer (`resolvers/`) translates a person/company name into works
to search for (AniList today; TMDB/IGDB/Jikan planned). A provider opts in by
declaring `creator_facets` (e.g. anime director/studio). Facet key + creator
name persist in history as `kind="creator"` entries.

## Store

`store.py` is the single owner of `filter_state.json`: machine-stable location,
legacy-copy consolidation, in-memory cache, dirty flag, and flush at exit + at
destructive sites. Everything above it (`state.py` toggles/settings/history,
`stats.py` counters) goes through `store.read()` / `store.write()` /
`store.flush()` and never touches the file. See
[ADR-0002](docs/adr/0002-single-store-for-persistence.md) and
[ADR-0006](docs/adr/0006-machine-stable-state-path.md).

## Credentials

Optional per-site logins/API keys, read from environment variables or
`subtitle_credentials.json` with environment taking precedence.

`credential_registry.py` is the integration seam: each `CredentialSpec` owns
typed fields, required/optional rules, display metadata, status/save/clear
semantics, and one lazy verifier adapter. `credentials.py` owns generic
environment/file storage; `ui/credentials.py` owns rendering and interaction.
See [ADR-0005](docs/adr/0005-credential-registry-owns-integration-metadata.md).
