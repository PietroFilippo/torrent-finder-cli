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
Named profiles live under `settings.search_profiles`, with stable IDs, unique
display names, an active ID, and independent combined snapshots. Each remembers
selected slugs, per-provider engine modes/required and preferred presets,
shared name include/exclude rules, and result order. The former
`settings.combined_search` is read as Default until an explicit save migrates it;
it then mirrors the active profile for older versions. Initial settings
copy solo settings except Anime resolution presets. No fresh Anime search
requires a resolution; explicitly saved resolution choices remain respected.
The profile editor commits all nested drafts together. History replay is detached
from named profiles; saving its settings creates a separate History search profile.
CLI `--profile` and `--providers` select/override a session without changing saved
settings. See [ADR-0013](docs/adr/0013-combined-provider-search.md) and
[ADR-0015](docs/adr/0015-named-profiles-and-preset-preferences.md).

Searches retain provider/category boundaries. `SearchSession` owns attempts keyed
by provider/query group, engine, expanded query and page. One coordinator commits
completed attempts; six engine invocations share its request budget. Initial
tasks are interleaved across provider/query groups so one provider's extra
engines cannot occupy the entire queue. `SearchControl` limits each initial,
retry or pagination action to 30 seconds and scopes shorter request deadlines
to engine threads. `search_request` leaves calls outside search sessions and
downloads unchanged. Partial results survive a deadline or Enter (show results
now). Esc discards an initial search; stopping a retry/page action retains
received rows. Late workers cannot mutate a completed action.
Progress reports providers finished, distinct results ready, and pending names.
Shared rules run before per-provider hash deduplication through `result_filter`;
they match names only. Search errors become notices alongside partial results.
History's optional `search_profile` snapshots reproduce combined settings.
Creator facets stay on concrete providers. Keyword, creator and alternate-title
flows share the session executor. `SearchResults` is a list with notices and a
session reference (`CombinedResults` remains a compatibility alias). The result
table can show an empty list while keeping diagnostics and retry available.
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
keeps the originating tracker as result provenance. `SearchEngine.page_fn` and
`initial_page` opt into deeper retrieval. Nyaa's RSS covers catalog page 1;
subsequent requests use chronological catalog pages. Knaben pages by 50 source
hits, before adapter filtering. `PageRows.has_more` drives exhaustion. Sessions
retain failed page cursors for targeted retry and cap each click at 24 pages,
with ten pages per source/query. Other engines explicitly report deeper
retrieval unavailable. UI refresh maps cursor and checkboxes by result identity,
then reapplies the current refinement and ordering.

`search_diagnostics.py` scopes request evidence to each engine worker through a
context variable. Transport errors swallowed by legacy adapters still appear
as search failures. Diagnostics distinguish results, empty/filtered responses,
missing or rejected login, other login errors, source errors, timeouts, skipped
Auto engines and Off engines. Counts describe normalized rows before dedup and
first exclusion at each ordered filter stage. A response with rows plus failed
requests remains retryable; earlier rows are retained. Generic errors never
include request URLs, headers or credential values. Credential configuration
status is labelled separately from verification, using the existing registry.
See [ADR-0017](docs/adr/0017-resumable-search-and-title-identification.md).

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
unchanged source still selects the acquisition adapter. Recommended order uses
title relevance, then the number of preferred presets matched in the originating
provider, preserving provider ordering for equal scores. Explicit result sorts
override that ranking without changing acquisition indexes.

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
Applied in order: provider defaults → required presets → CLI flags.
A `FilterPreset` is a named config with an Off / Require / Prefer selection.
`active_presets` retains required presets for compatibility; `preferred_presets`
scores matching rows without excluding others. Old active presets remain required.
Preferences choose the best alias before hash deduplication and break relevance
ties in Anime/combined searches. A required language filter is never relaxed by a
preference. Provider settings also persist `result_sort`; combined profiles have
their own overall sort. The table's `f` refinement changes only that result view.
See [ADR-0015](docs/adr/0015-named-profiles-and-preset-preferences.md).

A required or preferred preset may also shape the search itself, not just the rows it returns
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

## Resolver (creator and title search)

The resolver layer (`resolvers/`) translates a person/company name into works
to search for (AniList, TMDB, IGDB, Jikan, Open Library and keyless fallbacks). A provider opts in by
declaring `creator_facets` (e.g. anime director/studio). Facet key + creator
name persist in history as `kind="creator"` entries.

`resolvers/titles.py` identifies individual works using AniList (Anime/Manga),
TMDB (Movies/Series), IGDB (Games), or Open Library (Books). `TitleMatch` pairs a
catalog-local ID with the existing `Work` contract. Year, format, author/platform
hints and ID keep same-name works selectable separately. One selected work's
extra names are fetched on demand; lookup errors are distinct from no matches.
The UI offers applicable catalogs for the selected providers, retains explicit
credential requirements, and permits manual names for every provider. Users
review at most six chosen aliases before release search; catalogs are capped
at three user-requested pages. Unicode/whitespace/case normalization removes
duplicate names without inventing translations. The chosen query list persists
in keyword history's optional `queries` field and survives settings transfer;
ordinary keyword entries with the same display title remain distinct. Creator
fan-out also bounds aliases per Work to six and preserves their title provenance.

`resolvers/topics.py` maps a keyword phrase to explicit catalog vocabulary, then
retrieves matching `TitleMatch` works. AniList term descriptions can match a phrase
whose words differ from the label (time travel → Time Manipulation). The picker
requires the user to choose the catalog term. AniList tags require 60% relevance;
all chosen genres/tags are checked on returned rows too. TMDB movie/TV discovery
uses genre/keyword IDs; IGDB combines genre/theme/mode/keyword IDs with AND.
Open Library uses a single subject. Failed or malformed responses are errors,
not empty matches. Software purpose discovery is unsupported.

`ui/discovery.py` bounds a journey to three catalog pages, three selected works,
two names per work, and an explicit release-query review. Combined searches clone
the profile and intersect its selected providers with catalog compatibility;
the original selection is unchanged. The review names the effective providers.
Searches use the existing session executor and persist exact queries in history.
See [ADR-0018](docs/adr/0018-client-handoff-and-topic-discovery.md).

## Torrent client

`qbittorrent.py` implements optional WebUI API v2 authentication, duplicate
checks, additions and read-only client progress. URL/login values belong to the
credential registry and separate credential transfer. Each explicit flow owns a
cookie session, uses eight-second requests, validates the endpoint response and
does not follow redirects or automatically retry mutations. Acquisition adapters
expose `client_payload` for magnets or torrent files; direct downloads have none.
Torrent identities hash the original bencoded info bytes. An acknowledgement
without client confirmation stays pending, and ambiguous failures advise checking
the client. Existing torrents are never moved or recategorized. The UI sends full
torrents after destination review and shows timestamped client snapshots with R
to refresh. Client API progress is separate from method-completion statistics.

## Store

`NameRules` (`name_rules.py`) is the portable, name-only user rule contract:
all/any normalized words, a consecutive-word phrase, and excluded words. It
runs before hash deduplication in both solo and combined searches. Preset
`FilterConfig` keeps its existing source-aware semantics for repack presets.
Anime's `nyaa_category` is a saved source scope; Manga expresses scopes through
separate EN / Non-English / Raw engines (`3_1` / `3_2` / `3_3`). Language-name
checks remain evidence from tags, never track verification.

`bookmarks.py` stores search snapshots or complete result mappings under the
top-level `bookmarks` list. Stable IDs identify saved entries; canonical result
identity prevents duplicates and gates refresh updates. Missing refreshed rows
retain their old handles and fetched time. Reopening uses the acquisition seam;
comparison uses the existing table and original result indexes. `result_details`
provides offline listing metadata and separately labelled filename hints.

`store.py` is the single owner of `filter_state.json`: machine-stable location,
legacy-copy consolidation, in-memory cache, dirty flag, and flush at exit + at
destructive sites. Everything above it (`state.py` engine modes/settings/history,
`stats.py` counters) goes through `store.read()` / `store.write()` /
`store.flush()` and never touches the file. Explicit bookmark/import transactions
use `store.commit(candidate)`: write/fsync a unique sibling temporary file,
atomically replace, then update the cache. Failures preserve the prior file and
cache; unreadable authoritative files block replacement and legacy migration.
Ordinary flush uses the same atomic writer while keeping its fail-silent API.

`settings_backup.py` validates versioned transfer documents, allowlists portable
settings, prepares detached merge/replace candidates and previews, and excludes
credentials from normal exports. Separate credential documents go through the
credential store's atomic writer. Import resets omitted runtime provider options
before reloading persisted preferences. See
[ADR-0016](docs/adr/0016-portable-settings-and-saved-results.md),
[ADR-0002](docs/adr/0002-single-store-for-persistence.md) and
[ADR-0006](docs/adr/0006-machine-stable-state-path.md).

## Launcher

`torrent-finder` is the canonical package command. `launcher_alias.py` owns the
fixed quick-command presets, install-aware forwarding targets, collision and
ownership checks, and optional Windows user-PATH update. `ui/launcher.py` owns
the selector and confirmation flow. See
[ADR-0007](docs/adr/0007-managed-terminal-command-presets.md).

## Terminal Layout

Main and What's Next menus expose general quick actions, which contain bookmarks.
`main._quick_actions_flow` receives an optional provider: search-specific actions
choose a scope only when it is absent. A provider-bound entry keeps that scope.
`_bookmarks_flow` shares reopening, saved searches, comparison and refresh across
these entry points. Expanded result rows retain the normal background and use
the arrow/bold style for focus. Short menus omit long random tips to preserve
room for their choices. What's Next has unique case-insensitive letter shortcuts
and Tab for quick actions; its footer responds to viewport changes.

`ui.prompts.download_complete_prompt` offers Continue or Back after actions from
the download menu. Back (including Esc/Ctrl+C) returns to the same `TorrentSession`
or batch selection; it never repeats a handoff. Summary text stays in the selector
context so compact layouts retain it. `_batch_handoff` and `_batch_aria2` return
the navigation choice to `_batch_flow`. Failed downloads keep their error output
until acknowledged, then return to download options.

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
are failures even when package version metadata changed. A separate read-only
console viewer observes the job ID and waiting/installing/final states; closing
it never cancels the hidden worker. After a successful interactive update, the
worker waits three seconds and starts the updated package in a fresh Python
process and Windows console. The viewer shows the countdown, then closes without
a keypress. Reopening failure preserves the successful install result and asks
the user to open the app manually. Failed installs never trigger reopening.
Startup leaves an active countdown report for the worker to finish.
The viewer can read an archived completion report if
startup consumed it first. Failure to open the viewer leaves the queued job intact.

`ui/update_progress.py` renders an indeterminate activity bar, elapsed time, and
the actual outcome. Git/non-Windows package updates use the same display inline
and redirect installer output to the local log; binaries open Releases.
`--preview-update [success|failure]` bypasses normal startup, settings loading,
usage stats, and installers. `scripts/preview_update.py` exports a browser replay
from the same renderer for visual QA. Neither preview changes update status or
opens the application; both simulate the three-second success countdown.
