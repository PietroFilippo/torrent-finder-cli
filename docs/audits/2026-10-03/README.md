# Provider coverage audit — 2026-10-03

**Baseline:** v0.7.0, commit `c35280d4f7976fa1265b857c6c045d257d5ca711`.
**Outcome:** the audit is complete. Fix Online-Fix's search error handling first;
investigate its shallow search and Books relevance next. Keep the working anime
and manga defaults. F-Droid is the strongest measured optional addition, for a
limited part of Mobile. No new provider, product behavior, or release was added
by this research. The decisions and follow-up work are preserved below.

## Evidence and scope

- 352 queries: 32 for each of all 11 individual providers. Each has 24 titles,
  products or artists, seven spelling/language/edition variants, and one synthetic
  negative. This is a purposive sample, not a random sample of a catalog.
- 33 provider/engine combinations, including every default On, Auto and Off
  engine: **1,056 initial matrix cells**. Of those, 812 were live searches, 40
  reused an identical shared-source query, and 204 were explicitly left unknown
  after a source circuit breaker opened. Unknown cells are not empty searches.
- 79 follow-up engine measurements: 55 distinct Online-Fix queries at a slower
  pace, nine selected repeat controls, eight deeper-page checks, six Nyaa category
  checks and one shortened-query control. **1,135 engine records** in total.
- Four additional live combined searches cover all 11 providers. Additional
  research consists of 24 F-Droid searches, one Gutenberg metadata catalog
  download compared against 32 book cases, four Internet Archive searches,
  14 Knaben v2 requests, and five Online-Fix source comparisons.
- Offline replay uses the real `SearchSession` with saved raw rows: default and
  all-On settings for all 352 cases, 44 local prefer/require comparisons, and six
  pairs of alternate names. Network access is forbidden during those replays.
- Live engine measurements ran **04:37:56–05:07:41 UTC on October 3**
  (01:37:56–02:07:41 in America/Sao_Paulo). The engine records contain 2,051 HTTP
  observations; these include redirects and retries and are not 2,051 independent
  searches. Combined/candidate/source-comparison traffic is stored separately.

The corpus covers popular/niche and older/recent works; Portuguese, English,
other languages and native scripts; Saki and other ambiguous titles; sequels,
numeric spellings, accents, punctuation and capitalization; resolutions, batches,
volumes, editions, platforms and repacks. Individual cell scenarios are in
[cases.json](cases.json); the exact engine defaults/categories and configured
credential booleans are in [inventory.json](inventory.json).

RuTracker and Madokami credentials were configured; Online-Fix credentials were
not needed for public search. TMDB and IGDB credentials were configured but were
not used by this provider audit. Controlled tests cover missing and rejected
credentials without deliberately submitting invalid credentials to live sites.
Settings and APIBay cache were isolated, and live APIBay cache reuse was disabled.
The user's real settings, credentials and cache were verified unchanged.

### How to interpret the numbers

“Title candidate” means a normalized title/alias match after explicit exclusions
for known sequel and Saki collisions. It **does not establish relevance, edition,
language, safety, or downloadable availability**. Names are rescored against the
final manifest; aliases/exclusions were refined after inspecting responses. This
is diagnostic grading, not a preregistered benchmark. Requested variant tokens
have separate counts. Unsupported spellings can produce false negatives and
long descriptions or derivative works can produce false positives.

An 88-row, deliberately selected top-rank sample was also manually judged by
listing identity: 21 relevant, three bundles containing the target, and 64 other
products, sequels, derivatives or unrelated works. This sample deliberately
includes all 50 misleading Knaben Saki rows. **Do not extrapolate its error rate**
to the whole corpus. All individual judgments are in
[manual-relevance.json](manual-relevance.json). No general recall percentage is
claimed: the true available catalogs are not known.

The results are listing discovery. Madokami rows can be folders, other direct
sources can be intermediate pages, and reported seed counts can be stale.
Payload resolution, actual peers, installability, file completeness and content
downloads were not tested. The negative controls returned zero rows in all 26
initial cells that could run; seven other negative cells stayed unknown.

## Results by provider

Each denominator below is **31 nonnegative queries**, including variants of the
same work. Counts describe offline replay of measured source responses, with the
paced Online-Fix results substituted for its contaminated initial pass. “All On”
means the union of observed rows, **not complete source availability**: optional
SolidTorrents was unavailable for most cells. Replay treats unavailable sources
as supplying no observed rows, so Auto outcomes are conditional when an On source
was unavailable. Exact uncertainty and contributing source IDs are retained in
the replay data.

| Provider | Default candidate queries | All-On candidate queries | Finding and decision |
|---|---:|---:|---|
| Movies & Series | 30 | 30 | Knaben fills many APIBay/Nyaa gaps. Translated titles help; `Finding Nemo pt-br` is unresolved. Keep defaults; improve query review, not blanket source expansion. |
| General Games | 27 | 27 | FitGirl and Knaben are complementary; Online-Fix shares the dedicated catalog. Native-script/platform/repack suffix queries remain weak. Reuse canonical names and fix Online-Fix centrally. |
| Online-Fix | 24 | 24 | Confirmed cooldown, search-window and query failures. An adapter fix is warranted; another game catalog cannot repair this source's misleading diagnostics. |
| FitGirl | 24 | 24 | Canonical title searches work; `Baldurs Gate 3` and appended `fitgirl`/platform terms can miss the canonical listing. Accept source scope, offer canonical-title fallback. No additional source is needed inside this dedicated provider. |
| Desktop Software | 26 | 26 | APIBay supplies title candidates for only eight queries; Knaben supplies 26. SolidWorks, Ubuntu 24.04 and several modifier/native queries remain unresolved. Evaluate Knaben-first latency; do not call these catalog absences. |
| Mobile / Android | 21 | 21 | APIBay supplies one candidate query; Knaben supplies 21. Genuine sampled gaps for three FOSS apps are filled by F-Droid. An optional F-Droid adapter is justified if Android app coverage is a priority. |
| RuTracker | unknown | unknown | Five initial probes encountered an anti-bot challenge; 27 cells were skipped. Configured credentials could not establish access. Fix challenge reporting; catalog reach remains unmeasured. |
| Anime | 31 | 31 | Nyaa finds 30 queries and default fallback covers the remaining one. Saki ranks correctly on Nyaa; Knaben is noisy for this word. Keep Nyaa first and preserve the current title controls. |
| General Manga | 28 | 28 | English/raw/non-English categories are useful complementary views. `Yokohama Shopping Log` fails while `Yokohama Kaidashi Kikou` works. Prefer aliases/categories before a new source. |
| Madokami | 27 | 27 | Authenticated discovery works, but folder/alias matches can lead to unrelated directories. Chapter, batch and language suffixes need directory browsing. Accept that scope and improve work disambiguation if desired. |
| Books | 28 | 29 | The extra candidate is a concrete Auto-fallback suppression case. Libgen title noise and variant matching matter more than another broad source. Gutenberg is a useful optional classics route. |

Per-engine status distributions, raw/kept/title-candidate counts, candidate ranks,
latency ranges/medians/p95s and scenario-group totals are in
[summary.json](summary.json). The readable exhaustive engine table is
[engine-results.csv](engine-results.csv). Per-case source contribution and hashes
unique to each observed engine are in [replays.json.gz](replays.json.gz). “Unique”
there means absent from the other measured responses for that case; it does not
mean unique to that source's entire catalog.

## Findings that need attention

### 1. Online-Fix silently treats a cooldown as a successful search

A normal Valheim search followed about one second later by Palworld returned
HTTP 200 with the message “Вы сможете воспользоваться поиском через 10 секунд.”
(search can be used again in ten seconds). The main result area was empty. The
current parser scans the entire page, so it nevertheless returned a Palworld
sidebar entry. Other cooldown pages yield an apparent empty search.

[cooldown-evidence.json](cooldown-evidence.json) records the message, hashes of
the observed public pages and an offline replay of the original parser. The
initial Online-Fix pass is preserved but is **not reliable coverage evidence**.
All 55 distinct queries used by General Games and Online-Fix were repeated with
11-second request spacing. Dedicated Online-Fix recovered from two initial
result-bearing cells to 24. No cooldown was detected in the paced repeats.

**Necessary fix:** recognize DLE cooldown/error pages, report a retryable source
failure, parse only the actual search-result area, and share a source cooldown
across concurrent provider searches. Respect the action's cancellation/deadline;
do not hold a worker for an unbounded retry. Reuse identical shared-source work
in combined searches where practical. Merely increasing a timeout is insufficient.

### 2. Some Online-Fix misses are query/window failures

`Raft` returned 21 other listing IDs on the source's first search page and 21 on
its second. Neither contained Raft's ID `16179`, while the exact
[Raft source listing](https://online-fix.me/games/survival/16179-raft-po-seti.html)
returned HTTP 200 with the expected title. The quoted query `"Raft"` did not
solve it. This is a demonstrated discovery gap, not absence from the catalog.
The current adapter has no deeper-page operation for this source.

Both `Don't Starve Together` and `Dont Starve Together` returned no rows; the
bounded follow-up `Starve` returned `Dont Starve Together Po Seti`. A conservative
shorter-query fallback can help, followed by target-title validation. Adding
arbitrary edition/language suffixes is particularly ineffective on these listing
searches. See [source-comparisons.json.gz](source-comparisons.json.gz) and the
repeat-4 engine record.

**Worth fixing:** offer bounded, explicit deeper retrieval and a reviewed shorter
title fallback. Preserve “not found in this window”; do not claim catalog absence.
The exact page containing Raft was not sought beyond page two.

### 3. Books can return the wrong work and suppress a useful Auto source

For `Tomorrow and Tomorrow and Tomorrow`, Libgen returned other works, including
Thomas Sweterlitsch's *Tomorrow and Tomorrow*. Those raw rows suppress Knaben Auto
before local filters or work relevance are considered. Knaben independently
returned *Tomorrow, and Tomorrow, and Tomorrow by Gabrielle Zevin EPUB*, first
in that engine's result list. All-On replay therefore adds one target candidate.

The first five Libgen results for *Pride and Prejudice* were variations/derivative
works rather than Austen's original. Madokami's *One Piece* search similarly
started with *Ohana Moyou no One-Piece*, with the intended directory second.
Movies' Matrix search included several sequels; software's Photoshop search
started with Lightroom. These are source/work-ranking problems despite nonempty
searches, and explain why lexical hit rates are optimistic.

**Useful improvement, not an emergency default change:** consider explicit work
identity/author matching and a convenient retry with Knaben On. Revisit Auto's
raw-row condition only with regression tests and clear semantics. The current
rule is intentional and already characterized by tests; this audit identifies
its tradeoff rather than a newly introduced regression.

### 4. APIBay costs many retries for limited incremental coverage

Across its 224 initial cells, APIBay generated 1,292 HTTP observations (1,272 HTTP
200, 20 transport outcomes without status). Most healthy empties were still
empty after the existing spelling/category fallbacks. Cache was disabled here;
the app's last-known-good cache remains useful but is not proof of a live hit.
Software, Mobile and Manga get far more candidate queries from Knaben.

**Investigate before changing defaults:** compare Knaben-first against the
current On-then-Auto policy for those providers with a small repeated latency
test and APIBay's unique listing contribution. This audit supports that trial,
but not removing APIBay or globally enabling every engine.

### 5. Access failures must remain distinct from empty catalogs

RuTracker's five probes hit a 403 challenge and a combined search reported a
login error while retaining other providers' rows. This does not show that the
credentials are incorrect. A specific challenge/access-blocked diagnostic would
be more useful; do not bypass the challenge or retry it aggressively.

SolidTorrents redirected through BitSearch and eventually returned 429. Its
initial 192 cells comprise 12 results, two timeouts, one rate limit and 177
unknown skipped cells. One later Matrix control worked again. Keep it optional
and respect cooldown/Retry-After; the audit cannot grade its full coverage.
BitSearch is not an independent new catalog in this configuration.

## Existing features that worked, and limits to accept

- **Saki:** Nyaa's first row was `[Nozomi] Saki (720p Complete BD)`; its first five
  checked rows describe the requested series or a containing bundle. Knaben's
  first 50 were other shows, chiefly *Koko wa Ore… Saki ni Ike…* and *Tenkou-saki…*.
  Do not replace Nyaa with Knaben as Anime's primary source.
- **Paging:** Saki Nyaa pages two/three contained 75/60 identities absent from
  the initial response. These are independent comparisons with page one, not
  additive claims. One Piece English manga pages two/three each added 75
  identities relative to page one. Knaben Saki pages two/three each added 50
  identities, with continued title noise. Knaben Dune book pages two/three were
  empty. More rows are not necessarily more relevant works.
- **Language categories:** Saki non-English/raw checks returned 123/150 rows,
  all distinct from its initial English-category identities. Naruto also gained
  other-language/raw rows. Category routing is working; it does not certify that
  a particular release includes Portuguese audio/subtitles.
- **Alternate names:** replaying `Finding Nemo` plus `Procurando Nemo`, or
  `Frieren Beyond Journey's End` plus `Sousou no Frieren`, expands observed
  listings while deduplicating shared identities. Capitalized Lethal Company
  queries collapse to one listing. Native names and spelled-out numbers are not
  universally supported; review catalog names instead of assuming translation.
- **Prefer/require:** all 22 prefer probes retained the original eligible row
  count; 17 of 22 require probes removed rows. Requiring `apk` removed all 21
  observed Stardew Valley rows despite Android scope; requiring `c001` removed
  Madokami's directory rows. These are expected literal/metadata limitations,
  not reasons to relax a user's requirement. These were local filter replays,
  not live tests of every built-in preset's query expansion.
- **Combined searches:** Saki returned 312 rows in 2.906 s despite RuTracker's
  failure; Dune returned 176 in 3.109 s; VLC returned 97 in 3.078 s. Elden Ring
  returned four deduplicated rows with shared-provider provenance in 22.218 s.
  That game timing includes audit pacing of duplicate Online-Fix requests and
  must not be advertised as ordinary interactive performance.
- **Negative controls:** no live/reused initial negative returned any rows.
  Near matches still produce substantial noise, as the manual samples show.

## Additional-source decisions

| Candidate | Observed additional value | Access / maintenance | Decision |
|---|---|---|---|
| F-Droid | Five verified target app identities among 24 sampled mobile titles: VLC, OsmAnd, Organic Maps, K-9 Mail, AnkiDroid. The last three had no observed current-engine candidate; the first two overlap. | Public documented search API and signed repository indexes; distinguish real packages from plugins/remotes and validate provenance before future acquisition. | **Best optional addition.** Three new sampled app targets; does not fill the commercial-games gap. |
| Project Gutenberg | Verified originals for Pride and Prejudice, Frankenstein, Dracula, Metamorphosis and Dom Casmurro, plus a German Metamorphosis route missed by the `Die Verwandlung` query. The five works were already observed through existing queries. | Public metadata catalog; use its CSV/RDF data instead of scraping search pages. Edition/language matching still matters. | Optional clean classics/Portuguese route, **not necessary for general book breadth**. |
| Internet Archive | Four exploratory title searches; Dom Casmurro overlaps existing coverage, Night of the Living Dead produced listings, and the broad Metropolis query was noisy. The Left Hand of Darkness returned criticism/derivatives and a restricted item, not an established usable original. | Public metadata API; access restrictions and file manifests require per-item checks. | Defer a general adapter. No measured case justifies making it a priority; Night of the Living Dead was exploratory and has no baseline comparison here. |
| Knaben v2 | Fourteen successful calls covering seven queries, with/without zero-seed rows. Same meta-index; substantial identity overlap, not a new catalog. | Official GET API supports cacheable searches. New defaults exclude zero-seed rows: Blender fell from 11 rows with `dead` to one without it; Dune Books fell from 24 to nine. | **Plan a compatibility migration**, preserving explicit category, safety and zero-seed semantics. Do not blindly switch endpoints. |
| Direct broad indexers / BitSearch | Existing Knaben responses already cite Nyaa, TPB, RuTracker, YTS and 1337x origins; SolidTorrents reaches BitSearch. | Direct integrations add separate parsing/access/rate-limit maintenance. No direct incremental-coverage experiment for another broad indexer was established here. | No evidence-based reason for blanket additions now. Reconsider against a specific unresolved target and a measured unique match. |

F-Droid's `Minecraft`, `Tasker`, `Signal` and similar full-text responses include
related tools; those were **not** counted as the original applications. Gutenberg
lexical matches for `1984`, `Dune` and `Piranesi` included unrelated titles, and
`Alice in Wonderland` included adaptations/illustrations. They were excluded from
the verified-original count. Candidate raw responses are retained for review.

Current primary references (read October 3, 2026):

- [F-Droid APIs](https://f-droid.org/docs/All_our_APIs/) and verified package IDs
  [Organic Maps](https://f-droid.org/en/packages/app.organicmaps),
  [K-9 Mail](https://f-droid.org/en/packages/com.fsck.k9),
  [AnkiDroid](https://f-droid.org/en/packages/com.ichi2.anki).
- [Gutenberg metadata guidance](https://www.gutenberg.org/ebooks/offline_catalogs.html)
  and [published feed directory](https://www.gutenberg.org/cache/epub/feeds/).
- [Internet Archive developer portal](https://archive.org/developers/) and
  [automated access guidance](https://archive.org/developers/bots.html).
- [Knaben v1](https://knaben.org/api/v1/) and
  [Knaben v2 parameters and migration rationale](https://knaben.org/api/v2/).

## Prioritized follow-up, without authorizing implementation

| Priority | Action | Is work needed? | Completion criterion |
|---|---|---|---|
| P1 | Online-Fix cooldown/error detection, result-area parsing and shared pacing | **Yes: demonstrated misleading outcomes.** | Cooldown is retryable; sidebar rows never impersonate search results; cancellation remains prompt; repeated queries recover without flooding. |
| P1 | Explicit RuTracker challenge and SolidTorrents rate-limit handling | **Yes for diagnostics/resilience; no catalog conclusion.** | Clear blocked/rate-limited status, bounded retry, preserve partial results; re-audit RuTracker only when ordinary access works. |
| P2 | Online-Fix query fallback and bounded paging | **Yes if reliable discovery is expected.** | Raft and Don't Starve controls find their known listings or accurately state the inspected search window; no silent endless paging. |
| P2 | Book/work relevance and Auto fallback tradeoff | **Useful; current manual Knaben On is a workaround.** | Gabrielle Zevin case is discoverable without treating unrelated raw rows as sufficient; Austen/derivative and sequel cases remain distinguishable. |
| P2 | Knaben v2 compatibility evaluation | **Maintenance work justified.** | Parity checks cover categories, hashes, unsafe/adult exclusions, zero-seed inclusion and pagination before migration. |
| P3 | Knaben-first trial for Software/Mobile/Manga | **Evaluate, not yet a default-change mandate.** | Repeated end-to-end latency improves without losing the existing engines' distinct relevant identities. |
| P3 | Optional F-Droid provider/engine | **Worth doing for Android FOSS coverage.** | Three demonstrated gaps close, exact package identity is shown, official repository signatures/provenance are respected. |
| P4 | Optional Gutenberg route | **Nice to have.** | Original/author/language checks avoid derivatives and integrate catalog updates without search-page scraping. |
| Accept | Dedicated source scope, literal filters, unverified peers, blocked-source unknowns | **No blanket fix needed.** | Keep these limitations clear; use aliases, categories and existing paging before expanding source count. |
| Defer | General Internet Archive or another broad indexer | **Not justified by current incremental evidence.** | Require a specific target missed by current sources and a verified additional listing before prioritizing. |

All prior feature-batch items were already completed in v0.7.0. This report now
replaces the temporary local audit planning note; the local backlog and its
temporary agent pointer were removed after recording the results. Outstanding
recommendations are research findings, not unfinished authorized implementation.

## Reproduce and inspect

See [REPRODUCING.md](REPRODUCING.md) for opt-in commands, pacing, file schemas,
deterministic tests, offline reconstruction and important limitations. Checksums
of the evidence files are in [SHA256SUMS](SHA256SUMS).
