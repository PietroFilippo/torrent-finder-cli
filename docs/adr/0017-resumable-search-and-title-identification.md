# ADR-0017: Resumable search attempts and explicit title identification

Status: Accepted

## Context

Searches could return partial results and notices, but discarded the source
attempts needed to explain filtering or retry only failures. Deeper retrieval
also needed per-source cursors. Alternate-title searches multiply these same
operations and must preserve settings, origin and acquisition identity.

## Decision

Use one `SearchSession` executor for keyword, combined, creator and title-name
searches. It retains raw normalized rows and diagnostics per provider/query,
engine, expanded query and page. Only the coordinator commits finished attempts;
abandoned workers cannot update an old result set or a later retry. Each action
has six workers, a 30-second overall wait and the existing per-engine request
budget. Initial scheduling interleaves provider/query groups. Request tracing
uses a context variable, so adapters that catch network exceptions still yield
an actionable outcome without affecting downloads outside the session.

Filtering uses the existing ordered stages and reports first-exclusion counts.
Required filters are never relaxed by retry or pagination. Successful engine
requests are not repeated during targeted retry; failed requests can retain
partial rows. Auto still means zero raw On-engine rows, rather than zero rows
after local filters. Configured credentials and verified login remain distinct;
the existing registry and verification UI own credentials.

`SearchEngine.page_fn` opts a source into pagination. Nyaa starts at catalog
page 2 because its initial RSS covers page 1; Knaben uses 50-hit offsets before
adapter filtering. Exhausted or repeated pages stop, failed pages keep their
cursor, and Off/unused Auto engines are not activated. One explicit action
requests at most 24 pages, with a ten-page maximum per source/query. Other
sources report unavailable pagination. The table remaps selection and checks
by canonical result identity, then reapplies the user's sort/refinement.

Use the existing `Work` type for alternate-title identification, wrapped in a
`TitleMatch` with catalog and source ID. AniList, TMDB, IGDB and Open Library
provide category-specific candidates. Catalog lookup distinguishes failed
requests from no matches and fetches extra names only for the selected work.
The user reviews at most six names; no inferred translations or automatic
sequel/adaptation expansion occur. Browsing is capped at three catalog pages.
Manual names remain available for providers without an applicable catalog.
History stores the exact query list independently of a future catalog response.

## Consequences

Empty searches remain browsable so their diagnostics and actions are available.
Notices and list behavior remain compatible through `SearchResults`, also
exported as `CombinedResults`. Direct `BaseProvider.search` callers retain the
existing login exception contract when no rows survive.

Counts are per attempt before deduplication, not unique catalog coverage or a
claim that a source is unavailable. External indexes can change between page
requests. Native requests already in flight cannot be forcibly killed; their
results are ignored after the action ends. A retry/page action preserves data
received before cancellation. Title identification improves query coverage but
does not guarantee that releases belong to the chosen work or are available.

Validation covers targeted retries, late workers, shared concurrency, filter
counts, strict requirements, page exhaustion/failures, alias identity, history
transfer, result selection, and narrow-terminal rendering. Bounded live checks
are separate from the deterministic test suite.
