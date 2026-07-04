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

What a search returns: today a plain `dict` per row. Common keys: `name`,
`info_hash`, `seeders`, `leechers`, `size` (bytes, **stored as strings** and
re-`int()`ed by consumers), `source` (the engine/site that produced it),
`page_url`. Site clients add private handle keys only their own acquisition
path understands: `rt_topic_id` (RuTracker), `fg_post_url` (FitGirl),
`of_post_url` (Online-Fix), `mdk_path` (Madokami).

> Known debt: this contract is undocumented and stringly-typed — 85 `.get()`
> sites, defaults scattered (table.py falls back to `"Apibay"`). Planned fix:
> one typed `SearchResult`. Until that lands, treat this section as the
> contract.

## Acquisition

How a picked result becomes files on disk. Four styles exist:

1. **magnet-direct** — result carries a real `info_hash`; build a magnet
   (Apibay, SolidTorrents, Nyaa).
2. **magnet-lazy-resolve** — hash lives on the topic/post page, fetched on
   demand (`rutracker.resolve_info_hash`, `fitgirl.resolve_info_hash`).
3. **torrent-file-handoff** — no public magnet; fetch the `.torrent` and open
   it in the system client (Online-Fix; file host is referer-gated).
4. **direct-download** — no torrent at all; stream files straight to the
   download folder (Madokami, login required).

> Known debt: the style is chosen by re-testing `result["source"]` at ~11
> sites in `main.py` (`_magnet_for`, `_batch_handoff`, the `_*_pick`
> handlers). Planned fix: acquisition becomes part of the provider interface.

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

`store.py` is the single owner of `filter_state.json`: in-memory cache, dirty
flag, flush at exit + at destructive sites. Everything above it (`state.py`
toggles/settings/history, `stats.py` counters) goes through
`store.read()` / `store.write()` / `store.flush()` and never touches the file.
See [ADR-0002](docs/adr/0002-single-store-for-persistence.md).

## Credentials

Optional per-site logins/API keys (`credentials.py`), read from env vars or
`subtitle_credentials.json`. Used by subtitle providers and credentialed
sites (Madokami, RuTracker, Online-Fix optional login).

> Known debt: provider-credential metadata (fields, verifier) is split
> between `prompts.py:_CRED_PROVIDERS` and `credentials.py`. Planned fix: one
> credentials registry.
