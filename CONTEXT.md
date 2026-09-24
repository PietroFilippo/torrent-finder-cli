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
  `madokami`, `books`, `all`). Persistence (history, stats, settings), the `-t` CLI flag, and
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

**CombinedProvider** (`slug="all"`) orchestrates a selection of concrete
providers. It creates independent provider instances for its settings profile
and for each search invocation; it never borrows mutable registry instances.
Its profile lives under `settings.combined_search`: selected slugs, per-provider
engine modes/presets, and shared name include/exclude rules. Initial settings
copy solo settings except Anime resolution presets. No fresh Anime search
requires a resolution; explicitly saved resolution choices remain respected.
See [ADR-0013](docs/adr/0013-combined-provider-search.md).

Combined searches retain provider/category boundaries. Each selected provider
has an independent coordinator, processing its titles sequentially; six engine
invocations share the search's concurrency budget. `SearchControl` limits the
combined wait to 30 seconds and scopes shorter request/retry deadlines to engine
threads. `search_request` leaves standalone searches and downloads unchanged.
Engines publish filtered rows as they complete, so partial results survive a
deadline or Enter (show results now). Esc discards the search in the UI.
Progress reports providers finished, distinct results ready, and pending names.
Shared rules run before per-provider hash deduplication through `result_filter`;
they match names only. Search errors become notices alongside partial results.
History's optional `search_profile` snapshots reproduce combined settings.
Creator facets stay on concrete providers.
See [ADR-0014](docs/adr/0014-bounded-combined-search.md) for the latency correction
to ADR-0013's original coordinator scheduling.

## Engine

A search backend inside a provider (`SearchEngine` in `providers/base.py`):
Apibay, Knaben, Nyaa (per-category), or a site-specific scraper. A
provider fans a query out to all On engines concurrently, filters release
variants before merging on `info_hash`, and sorts by seeders. This preserves
language tags when indexers give the same hash different names. Engines are mode-configurable per
provider; the mode persists under the provider's slug.

Modes are explicit: **On** participates in every fan-out, **Auto** runs only
when all On engines produced zero raw rows before filtering, and **Off** is
not contacted unless an active preset explicitly requires it for that search.
An Auto engine also runs when there are no primary engines. APIBay
additionally keeps a bounded
last-known-good result set per normalized provider/query. Live search always
runs first; cached rows preserve `source="Apibay"` for acquisition routing
and carry presentation-only cache provenance. See
[ADR-0009](docs/adr/0009-apibay-last-known-good-and-emergency-engines.md)
and [ADR-0010](docs/adr/0010-knaben-and-explicit-engine-modes.md).

Knaben is the default Auto engine for public-tracker providers. Each provider
maps to Knaben's normalized categories; the adapter makes one bounded request,
asks the service to hide unsafe/XXX rows, accepts only valid info hashes, and
keeps the originating tracker as result provenance.

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

Combined rows additionally carry `provider_slug`, `provider_label`,
`matched_providers`, and `matched_queries` in `extra`. Copies protect cached
source rows from these annotations. Real 40-digit hex hashes deduplicate across
providers; other identifiers are scoped by source and URL/handle. The first
matching provider in registry order supplies the row, and all origins are kept.
`provider_for_result` selects download capabilities and pick statistics; the
unchanged source still selects the acquisition adapter. Title relevance orders
the combined table, preserving provider ordering for equal scores.

## Acquisition

How a picked result becomes files on disk. Four styles exist, each an adapter
in `acquisition.py` behind one interface
(see [ADR-0003](docs/adr/0003-acquisition-seam.md)):

1. **magnet-direct** — result carries a real `info_hash`; build a magnet
   (Apibay, Knaben, SolidTorrents, Nyaa, YTS — and any unregistered source).
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
keywords, plus optional `include_regex` and a name-only `name_predicate`).
Applied in order: provider defaults → active presets → CLI flags.
A `FilterPreset` is a named config the user toggles per provider; active
presets persist under the provider's slug.

A preset may also shape the search itself, not just the rows it returns
(see [ADR-0011](docs/adr/0011-presets-may-shape-the-search.md)):
`query_terms` fans one query out over extra spellings (`Toy Story` →
`Toy Story dublado`), and `require_engines` forces named engines On for the
duration of that search only — never persisted, never written back to the
engine's saved mode. Both are bounded in `providers/base.py`. This exists
because language is not a property of rows an English query returns: the
indexers file Portuguese releases under Portuguese release names, so
**Dublado (PT-BR)** has to ask different questions, not filter better answers.
APIBay retries keep the full title when a preset term is appended, so a
fallback never searches only for `dublado` or `pt-br`. `effective_engines`
is the shared source for the primary search and the search-screen status.

`language_tags.py` owns the Portuguese name predicates. Audio and subtitle
labels are interpreted separately; uploader names are not audio evidence.
The Brazilian preset requires explicit regional audio tags: `PT-BR`,
`Português Brasileiro`, etc. Generic Portuguese/dub tags and Brazilian subtitle
tags alone do not qualify. Tags remain a heuristic, not proof of track contents.

`result_view.py` owns title matching and index-preserving result refinement.
The table's `f` menu filters fetched rows and sorts them without changing their
acquisition identity. `uploaded_at` is a UTC epoch timestamp (0 = unknown),
provided by sources with an upload/publication date; last-seen is not upload time.
Anime prefers exact/prefix title matches. `nyaa.py` supplements short queries
with one popular-catalog page when RSS contains no exact title, optionally
excluding dominant unrelated title prefixes. Original RSS rows are retained.
FitGirl and Online-Fix require query words in their parsed title.

## Resolver (creator search)

The resolver layer (`resolvers/`) translates a person/company name into works
to search for (AniList today; TMDB/IGDB/Jikan planned). A provider opts in by
declaring `creator_facets` (e.g. anime director/studio). Facet key + creator
name persist in history as `kind="creator"` entries.

## Store

`store.py` is the single owner of `filter_state.json`: machine-stable location,
legacy-copy consolidation, in-memory cache, dirty flag, and flush at exit + at
destructive sites. Everything above it (`state.py` engine modes/settings/history,
`stats.py` counters) goes through `store.read()` / `store.write()` /
`store.flush()` and never touches the file. See
[ADR-0002](docs/adr/0002-single-store-for-persistence.md) and
[ADR-0006](docs/adr/0006-machine-stable-state-path.md).

## Launcher

`torrent-finder` is the canonical package command. `launcher_alias.py` owns the
fixed quick-command presets, install-aware forwarding targets, collision and
ownership checks, and optional Windows user-PATH update. `ui/launcher.py` owns
the selector and confirmation flow. See
[ADR-0007](docs/adr/0007-managed-terminal-command-presets.md).

## Terminal Layout

A viewport is the terminal's current width and height, which may change while
an interactive screen is open. `ui/layout.py` owns terminal-cell-aware
cropping and marquee primitives. Selectable rows remain one physical line so
cursor movement and height windowing are stable; contextual hints,
descriptions, footers, and result metadata may wrap.

The result table progressively removes columns as the viewport narrows and
shows hidden fields for the selected result in its caption. Selectors and the
result table watch live size changes. Streaming headers reserve their measured
wrapped height before subprocess output begins. See
[ADR-0008](docs/adr/0008-responsive-terminal-layout.md).

Short viewports use a one-line banner and tighter padding. Windowed selectors
show position in the border instead of extra “more above/below” rows and accept
PgUp/PgDn/Home/End. Action-only menus scroll too.
Search notices collapse to one line in short windows; `n` opens a notice
browser without resetting the result selection. Mixed results show provider
labels and selected-row provenance even when columns collapse.

## Credentials

Optional per-site logins/API keys, read from environment variables or
`subtitle_credentials.json` with environment taking precedence.

`credential_registry.py` is the integration seam: each `CredentialSpec` owns
typed fields, required/optional rules, display metadata, status/save/clear
semantics, and one lazy verifier adapter. `credentials.py` owns generic
environment/file storage; `ui/credentials.py` owns rendering and interaction.
See [ADR-0005](docs/adr/0005-credential-registry-owns-integration-metadata.md).

The credential file uses the same machine-stable directory as settings. Legacy
copies migrate only when the destination is absent, per integration, with newest
fields kept together. Read failures never become a writable empty store; writes
use an atomic replacement. Existing stable files, including explicit clears,
win over legacy copies. Madokami and RuTracker refresh sessions when credentials
change. `SearchError` carries actionable login failures through search fan-out
to the UI. See [ADR-0012](docs/adr/0012-stable-credentials-and-safe-updates.md).

## Updates

Windows pip/pipx updates run through `update_worker.py` after the parent process
exits, releasing the running launcher. A hidden helper writes output to a local
log and records the real exit status; startup consumes the report. Nonzero exits
are failures even when package version metadata changed. Other install types
retain their existing git/pip or Releases-page flow.
