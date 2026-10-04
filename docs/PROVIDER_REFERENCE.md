# Provider reference — tested October 3, 2026

This document describes **each provider as tested in v0.7.0**: its sources,
default settings, observed results, useful search patterns, limitations and
recommended changes. It is a dated evidence-based reference, not a promise of
permanent source availability. The [full audit](audits/2026-10-03/README.md)
contains the raw evidence, methodology and reproduction instructions.

The findings below have been recorded; the proposed product changes have not
been implemented. The original local backlog and temporary agent pointer remain
deleted.

## Reading the results

A **provider** is a category or dedicated source selected in the app. An **engine**
is one of the sources searched by that provider. Several providers reuse the
same engine; those are not independent catalogs.

- **On:** searched normally. **Auto:** fallback when the active primary engines
  return no raw rows. **Off:** available but disabled by default. Required
  presets can affect which engines run for a particular search.
- Each provider received 32 queries: 24 titles/products/artists, seven variants
  and one synthetic negative. Counts below use the **31 nonnegative queries**;
  multiple queries can refer to one work.
- A **title candidate** is a normalized title/alias match with known exclusions.
  It may still be the wrong work, edition, language or product. These numbers
  are not download success rates or catalog recall.
- Provider totals replay defaults over observed source responses. Engine totals
  test each source independently, including engines normally Off. They cannot
  be added because sources overlap. Online-Fix totals use the slower corrected
  pass. If a primary source was unavailable, its observed contribution is empty
  and the corresponding Auto replay is conditional.
- A blocked or skipped request is **unknown**, not proof of a missing title.
  Optional SolidTorrents coverage is incomplete throughout the table.
- “Paging” below describes engines exposing **Load more** in this build. The
  audit live-tested selected Nyaa and Knaben pages, not every provider's pages.
- Search result types describe the implemented acquisition paths; this audit
  did not download content, verify magnets/files, check peers or test installs.

The study retained 1,135 engine records from 352 queries, plus combined searches
and candidate-source probes. Of 1,056 initial matrix cells, 812 were live, 40
reused an identical shared-source query and 204 stayed unknown after source
failures. The audit's deterministic suite passed 409 tests; offline evidence
reproduction and private-file preservation were verified.

## Overview

| Provider | Default title-candidate queries | Overall assessment |
|---|---:|---|
| [Movies & Series](#movies--series) | 30/31 | Strong sampled discovery; translated titles and sequel identification matter. |
| [General Games](#general-games) | 27/31 | Complementary sources; shared Online-Fix issues affect it too. |
| [Online-Fix](#online-fix) | 24/31 | Confirmed cooldown, parsing and query problems need attention. |
| [FitGirl](#fitgirl) | 24/31 | Canonical titles work better than modifiers and altered spellings. |
| [Desktop Software](#desktop-software) | 26/31 | Knaben supplies much of the observed breadth. |
| [Mobile / Android](#mobile--android) | 21/31 | Several sampled gaps; F-Droid fills three specific app targets. |
| [RuTracker](#rutracker) | Unknown | Anti-bot access prevented a catalog assessment. |
| [Anime](#anime) | 31/31 | Keep Nyaa first; aliases, categories and paging are useful. |
| [General Manga](#general-manga) | 28/31 | Language categories and alternate names improve discovery. |
| [Madokami](#madokami) | 27/31 | Authenticated search works; folder and related-title matches need interpretation. |
| [Books](#books) | 28/31 | Relevance and Auto behavior matter; Knaben On adds one sampled target. |

Enabling every engine added a candidate for only one extra query in the observed
matrix, taking Books to 29/31. This does not establish that optional engines add
no coverage: many source cells were unknown, and additional editions of a title
already found do not increase the query count.

## Movies & Series

**Scope:** movie and television listings. The sampled corpus included popular
and niche films, older titles, series, Brazilian works, translated titles,
resolution suffixes and Portuguese-language tags. Results from these engines
follow the app's direct-magnet path; downloads were not tested.

| Engine | Default | Queries with a title candidate |
|---|---|---:|
| APIBay | On | 15 |
| Nyaa | On | 9 |
| Knaben | Auto | 30 |
| YTS | Off | 22 |
| SolidTorrents | Off | 2 observed; 30 cells skipped |

**What worked:** the default combination produced candidates for 30/31 queries.
Knaben filled many gaps left by APIBay and Nyaa. Searching both `Finding Nemo`
and `Procurando Nemo` expanded observed listings while deduplicating identities.
Brazilian/translated-title cases such as `Cidade de Deus` returned candidates.

**Limits:** `Finding Nemo pt-br` remained unresolved. That does not prove that a
Portuguese release is absent; appending tags can prevent the source from finding
the title. Matrix results included sequels and a containing franchise bundle.
YTS returned candidates for 22 queries but did not add a new target query beyond
the observed default combination. APIBay had four initial timeouts.

**Paging and source scope:** Knaben and Nyaa expose paging. Movies' Nyaa default
is category `4_1`, the live-action English category, not the Anime provider's
category. It should not be interpreted as a general replacement for movie/TV
indexers.

**Decision:** keep defaults for now. Improve translated-name review and
target/sequel ranking where helpful. No broad new movie source is justified by
this sample alone.

**Status (2026-10-04): ranking and typed tags implemented; engines unchanged.**
- Movies rank by `movie_title_score`. Release tags typed with the title don't
  count against it, numbers match words and roman numerals ("Part 2" = "Part
  Two"), and a year in the query must match.
- Replaying the audit's Matrix rows moves the first sequel from position 5 to
  34, with the original first. "Dune Part 2" and "Finding Nemo 1080p" now match
  their films.
- A tagged query ("Finding Nemo pt-br") also searches the bare title, and
  releases carrying the typed tags lead among equally good titles.
- PT-BR releases are usually named with the Portuguese title ("Procurando
  Nemo"). Searching that, or adding it through Identify title, stays the way to
  find them.
- The raw-row Auto rule stays for Movies: in the audit, the primary engines'
  rows already matched whenever they existed.

## General Games

**Scope:** game discovery across general indexes and dedicated release sites.
The provider mixes direct-magnet results with FitGirl post resolution and
Online-Fix torrent-file handoff; those acquisition paths were not exercised.

| Engine | Default | Queries with a title candidate |
|---|---|---:|
| APIBay | On | 3 |
| Online-Fix | On | 12, corrected paced pass |
| FitGirl | On | 24 |
| Knaben | Auto | 24 |
| SolidTorrents | Off | 1 observed; source then failed/rate-limited |

**What worked:** 27/31 queries had a default candidate. FitGirl and Knaben were
complementary. In a live combined search across General Games, FitGirl and
Online-Fix, Elden Ring produced four deduplicated rows retaining shared-provider
provenance.

**Limits:** native-script, spelled-out-number, platform and repack-suffix queries
were weak. Examples without a candidate included `Portal Two`, `Stardew Valley
linux` and `Cyberpunk 2077 fitgirl`. Their failure does not establish absence of
the underlying canonical game. Online-Fix's cooldown and query problems also
apply here because this provider uses the same source.

**Paging:** Knaben exposes Load more; the dedicated FitGirl and Online-Fix
engines do not expose deeper retrieval in this build. The combined Elden Ring
run took 22.218 seconds with audit pacing of duplicated Online-Fix requests;
this is not a normal interactive performance estimate.

**Decision:** fix Online-Fix once at the shared-source level. Prefer reviewed
canonical names to adding source/platform words to the title. Additional general
game indexes are not a demonstrated priority.

**Status (2026-10-04): the dedicated engines search the title; FitGirl shares requests.**
- FitGirl and Online-Fix drop source and platform words (`fitgirl`, `repack`,
  `dodi`, `online-fix`, `linux`, `pc`, …) before searching. The general indexes
  still receive them, because torrent names there often contain those words.
- Live after the change: `Cyberpunk 2077 fitgirl` and `Stardew Valley linux`
  return their FitGirl posts. `Portal Two` still finds nothing: FitGirl has no
  Portal 2 post, and the existing Apibay number-word retry is unchanged.
- FitGirl searches from both game providers are shared: a concurrent identical
  search waits for the first, and the same title within 30 seconds reuses its
  rows. A failed search is not reused. Online-Fix already worked this way.
- See FitGirl below for its spelling fallbacks.

## Online-Fix

**Scope:** dedicated game listings for the source's multiplayer/co-op offerings.
Search was public and worked without configured Online-Fix credentials. The
app discovers a post first and uses a torrent-file handoff later; a discovered
post is not proof that acquisition or multiplayer works.

**Engine/default:** Online-Fix On, with no other engine and no Load more support.
The corrected pass produced title candidates for **24/31** queries.

**Confirmed error-handling problem:** after a Valheim search, a Palworld search
about one second later received HTTP 200 with a message requiring a ten-second
wait. The actual result area was empty, but the parser returned a Palworld
sidebar entry because it scans the entire page. Other such responses can appear
as empty searches. HTTP success therefore did not mean search success.

The dedicated provider had only two result-bearing queries in the fast initial
pass. Repeating all 55 distinct queries shared by the two game providers with
eleven-second spacing recovered 24 dedicated-provider result-bearing queries,
with no detected cooldown. The fast pass remains archived but is unsuitable for
judging catalog coverage.

**Confirmed discovery gaps:** Raft's exact listing was accessible, while the
source's first two search pages each returned 21 other IDs and omitted it.
Quoting the title did not solve that. Both `Don't Starve Together` and `Dont
Starve Together` were empty, while the shorter `Starve` found the intended post.
The audit did not establish which later page contains Raft.

**Decision — work needed:** recognize cooldown/error pages, report retryable
failures, parse only the result area, and coordinate shared-source pacing.
Preserve cancellation and deadlines. Then investigate a bounded shorter-title
fallback and explicit deeper retrieval with target verification. Simply adding
another provider or increasing a timeout would not correct the misleading
outcomes.

Evidence: [cooldown replay](audits/2026-10-03/cooldown-evidence.json) and
[source comparisons](audits/2026-10-03/source-comparisons.json.gz).

**Status (2026-10-03): error handling, parsing and pacing implemented.**
- Rows come only from the search page's `news news-search` result blocks, never
  from the sidebar. Replaying the saved Palworld cooldown page now gives no rows
  instead of the sidebar entry.
- The DLE flood-control box (`поиском через N секунд`) is waited out once when
  the engine's time allows. Otherwise it is a retryable failure (`r`).
- HTTP errors and pages that are neither result pages nor search pages are
  retryable failures too.
- Online-Fix searches from both game providers pass through one gate. It keeps
  them 10 seconds apart, and an identical query within 30 seconds reuses the
  rows instead of a second request.
- A live zero-result search confirmed that empty searches still render the
  search form, so they stay "no results".
- The shorter-title fallback and deeper retrieval remain open. With a 10-second
  spacing and a 12-second engine budget, each extra automatic search would need
  its own retry.

## FitGirl

**Scope:** dedicated FitGirl game posts. The engine is also reused by General
Games, so those two views do not represent different catalogs. The app resolves
a post's magnet later; that step was outside this audit.

**Engine/default:** FitGirl On, no alternative engine and no Load more operation.
Title candidates appeared for **24/31** queries; the dedicated pass had 24
result-bearing searches and eight empty searches, including the negative.

**What worked:** canonical game-title searches returned useful posts. The
Cyberpunk 2077 control returned its Ultimate Edition listing and returned the
same result in the selected repeat.

**Limits:** `Baldurs Gate 3` missed despite the canonical `Baldur's Gate 3`
listing being discoverable. Added `fitgirl` and `linux` suffixes could also
produce empties. Lethal Company and Portal 2 were not found by their sampled
queries; this audit did not establish their absence from the whole catalog.

**Decision:** retain the dedicated-source scope. A reviewed canonical-title
fallback could help punctuation/modifier cases. There is no reason to add other
catalogs inside a provider specifically named FitGirl; use General Games when
broader discovery is wanted.

**Status (2026-10-04): spelling fallbacks implemented.**
- The site did return the `Baldur’s Gate 3` post for `Baldurs Gate 3`; the
  app's own title check dropped it over the curly apostrophe. Title checks now
  ignore apostrophes, so `Baldurs`, `Baldur's` and `Baldur’s` match each other
  (FitGirl, Online-Fix and the result-list search).
- When the title finds no matching post, at most two more searches run:
  1. the final number written the other way (`Civilization VI` →
     `Civilization 6`, `Final Fantasy 7` → `Final Fantasy VII`, `Grand Theft
     Auto 5` → `Grand Theft Auto V`). Spelled-out numbers (`Dying Light Two`)
     later moved to the search session's digit retry, which every provider
     shares;
  2. possessive endings dropped (`Baldurs Gate 3` → `Baldur Gate 3`). Posts
     from this broader search must still match the typed title.
- Live checks: `Dying Light Two` and `Civilization VI` (titled `Civilization
  6` on the site) find their posts with four requests in about 3 seconds.
- A failed first request is now a retryable failure instead of an empty
  result. Since the final review, an HTTP error page is one too, and a search
  that recorded any failure is not reused by the 30-second shared cache.

## Desktop Software

**Scope:** desktop application listings across the configured software
categories. The corpus included commercial and free applications, operating
system/platform terms, editions, portable variants and other-language spellings.

| Engine | Default | Queries with a title candidate |
|---|---|---:|
| APIBay | On | 8 |
| Knaben | Auto | 26 |
| SolidTorrents | Off | 1 observed; 30 cells skipped |

**What worked:** defaults yielded **26/31** candidate queries. Knaben was the
major source of observed title breadth. Knaben exposes paging; the other two
engines do not expose it in the app.

**Limits:** SolidWorks, Ubuntu 24.04, Photoshop portable, `Office português` and
the sampled Cyrillic Photoshop query had no candidate in the observed union.
These remain unresolved searches, not proven catalog absences. Photoshop's top
Knaben result was Lightroom, showing a product-identity/ranking problem. Claimed
software versions, platforms and installability were not verified.

**Decision:** test whether Knaben-first improves real search latency while
preserving APIBay's distinct relevant listings. Do not remove APIBay based only
on query counts. Product/platform disambiguation may be more useful than adding
another broad indexer.

**Status (2026-10-04): Knaben On beside APIBay; product and platform ranking.**
- Audit timings: APIBay averaged 5.4 s per program (often after empty retries)
  and returned rows for 8 of 32. Knaben averaged 0.8 s and returned rows for
  26. Because Auto waited for APIBay, most searches took both times in turn.
- When APIBay did return rows, most were not in Knaben's 50 (VLC 0/93, DaVinci
  Resolve 8/92, Ableton Live 21/88). So APIBay stays On, and Knaben is On beside
  it rather than Auto after it. Knaben can still be set to Auto.
- Live, `Photoshop` showed Knaben's rows after about 1 s. The search finished
  in 1.9 s, since this time APIBay answered quickly with nothing.
- Saved engine choices are kept. Profiles that saved the old default still say
  Knaben Auto until changed in Filters & engines.
- Ranking: the program counts as found when its name is followed only by
  details (version, year, edition, platform, language, packaging). Another name
  word means another product. Replaying the audit, `Adobe Photoshop` no longer
  starts with Photoshop Lightroom; Lightroom, Elements, bundles, plugin packs
  and AutoCAD LT rank below the program itself.
- A platform typed after the name (`mac`, `windows`, `linux`, `portable`)
  applies that preset for the search, searches the name alone too, and lists
  tagged releases first. The macOS preset now also recognizes "Mac" as a word.

## Mobile / Android

**Scope:** Android app/game listings, not general iOS coverage. The sample mixed
commercial games and apps with free/open-source apps, APK/OBB/modifier queries,
Portuguese and native-script queries.

| Engine | Default | Queries with a title candidate |
|---|---|---:|
| APIBay | On | 1 |
| Knaben | Auto | 21 |
| SolidTorrents | Off | 2 observed; 30 cells skipped |

**What worked:** defaults produced **21/31** candidate queries, largely through
Knaben, which exposes paging. Minecraft returned Android listings, although one
high-ranked result was Pixel Gun 3D rather than Minecraft itself.

**Limits:** several games and apps remained unresolved. Organic Maps, K-9 Mail
and AnkiDroid had no observed candidate from the existing engines. Requiring the
literal word `apk` removed all 21 observed Stardew Valley rows despite Android
scope, because a source category does not guarantee that token appears in a
listing. Reported versions and working APKs were not verified.

**Measured alternative:** among 24 mobile title probes, F-Droid returned five
verified target package identities: VLC, OsmAnd, Organic Maps, K-9 Mail and
AnkiDroid. VLC/OsmAnd overlapped existing discovery; **the other three fill
specific sampled gaps**. Minecraft utilities, Tasker plugins and signal-generator
apps were not miscounted as the original Minecraft, Tasker or Signal Messenger.

**Decision:** F-Droid is the clearest optional addition if Android FOSS coverage
is a priority. It would not fill commercial-game gaps. Show exact package identity
and use official repository provenance/signature verification for any future
acquisition. Also evaluate Knaben-first latency before changing defaults.

**Status (2026-10-04): Knaben first, app ranking, optional F-Droid.**
- Audit timings: APIBay averaged 5.6 s and returned rows for 1 of 32 Android
  queries (VLC, all four also in Knaben's). Knaben averaged 1.0 s and returned
  rows for 21. The defaults are now Knaben On and APIBay Auto. APIBay also runs
  when Knaben's rows are only other apps naming the query. Saved engine choices
  are kept.
- Ranking: the app itself (name followed only by version/edition/packaging
  details) ranks above look-alikes and add-ons. Names only inside parentheses
  or brackets (`Pixel Gun 3D (Pocket Minecraft Edition)`) and "… for Minecraft"
  add-ons rank below.
- Typed tags (`Minecraft obb`, `… apk`, `… mod`) apply the matching preset for
  the search, search the name alone too, and list tagged releases first. The
  "APK only" preset now explains that Prefer is usually better than Require.
- The iOS exclusion matched substrings, so it hid names such as "Studios" or
  "Kiosk". It now matches whole words, as does Desktop's mobile exclusion, which
  had hidden BIOS tools.
- **F-Droid engine (Off by default).** It searches F-Droid's public search API
  (about 0.8 s). Rows show the exact package: `VLC [org.videolan.vlc]` ranks
  above `VlcFreemote`, and Organic Maps (an audit gap) is found.
- A pick asks the package API for the suggested version and downloads that APK
  from `https://f-droid.org/repo/` over HTTPS, the files F-Droid's website
  links. Downloads from other URLs, or that end up on another host, are
  refused. A live download produced a valid APK.
- Some apps publish one build per CPU type (VLC 3.7.1 has four). The
  download is F-Droid's suggested build, and the done panel says so and links
  the package page for other device types.
- Verification: Android checks the APK signature on install. F-Droid's
  per-APK PGP signature (`.apk.asc`) is linked, not checked. F-Droid exposes no
  per-APK hash outside its large signed index, and checking PGP would require
  gpg plus F-Droid's key.

## RuTracker

**Scope:** dedicated RuTracker search. Credentials were configured during the
audit. The app normally discovers topic listings and resolves their magnets
later; successful access and acquisition were not established in this run.

**Engine/default:** RuTracker On, no alternative engine or app Load more operation.

**Observed availability:** five initial probes encountered an anti-bot challenge;
the remaining 27 cells were left unknown. A combined Saki search reported a
login error for RuTracker while retaining 312 rows from other providers.

**What cannot be concluded:** these outcomes establish neither poor catalog
coverage nor an incorrect password. They do not measure RuTracker's Russian,
older or niche content reach. Treat its result as **unknown**, not 0/31.

**Decision — work needed for diagnostics:** distinguish an access challenge from
rejected credentials, stop repeated blocked attempts, and retain other sources'
partial results. Reassess catalog coverage when ordinary access is working;
do not bypass the challenge or infer missing titles from it.

**Status (2026-10-04): diagnostics implemented; access still blocked.**
- A scripted request to `login.php` returns HTTP 403 "Just a moment…", which is
  Cloudflare's browser check; the forum index itself loads.
- The app now separates Cloudflare's check, rejected credentials, RuTracker's
  own captcha, an unreachable site and unexpected pages.
- A blocked login is reported as an access problem ("blocked"; not a password
  problem, and not counted as retryable). It is not attempted again for five
  minutes. A rejected login is not retried until the credentials change. A
  captcha waits five minutes too, since logging in once in a browser clears
  it (changed in the final review, which also applied the pause to an existing
  session and made passwords with accents or "€" safe to send).
- Other providers' results are kept, and the challenge is not bypassed. Catalog
  coverage stays unknown until ordinary access works.

## Anime

**Scope:** anime torrents. Nyaa defaults to `1_2` (English-translated anime);
other-language, raw and all-anime categories were separately sampled.

| Engine | Default | Queries with a title candidate |
|---|---|---:|
| Nyaa | On | 30 |
| Knaben | Auto | 28 |
| APIBay | Off | 9 |
| SolidTorrents | Off | 3 observed; 29 cells skipped |

**What worked:** the default combination supplied a title candidate for **31/31**
queries. For Saki, Nyaa placed `[Nozomi] Saki (720p Complete BD)` first. The first
five checked rows described the intended series or a containing bundle. English
and romanized Frieren names together expanded the observed listings.

**Important limitation:** Knaben's first 50 Saki results were unrelated shows
with “Saki” embedded in longer titles, chiefly *Koko wa Ore… Saki ni Ike…* and
*Tenkou-saki…*. More results and a broader index did not mean better relevance.

**Paging/categories:** both Nyaa and Knaben expose paging. Nyaa's Saki pages two
and three contained 75 and 60 identities absent from the initial response,
respectively. The non-English/raw Saki checks returned 123/150 rows, all distinct
from the initial English-category identities. These are listing comparisons,
not proof of a specified language track or usable peers.

**Decision:** keep Nyaa first and Knaben as a fallback. Preserve title controls,
alternate names, explicit category selection and Load more. This audit provides
no reason for a blanket expansion or a change of Anime's primary engine.

## General Manga

**Scope:** manga listings across translated, raw and non-English source views.

| Engine | Default | Queries with a title candidate |
|---|---|---:|
| Nyaa (EN), category `3_1` | On | 26 |
| Nyaa (Raw), category `3_3` | Off | 22 |
| Nyaa (Non-English), category `3_2` | Off | 13 |
| APIBay | On | 2 |
| Knaben | Auto | 28 |

**What worked:** defaults supplied candidates for **28/31** queries. The three
Nyaa categories provide complementary language/raw views. One Piece's first
English result was a volume/chapter collection, and its first five checked
rows described the intended manga.

**Limits:** `Yokohama Shopping Log` was empty while `Yokohama Kaidashi Kikou`
worked. `Twenty First Century Boys` and `Berserk português` had no observed
candidate. An empty spelling or language-tag query does not establish absence
of the work or a translation.

**Paging:** all three Nyaa engines and Knaben expose it. One Piece English pages
two and three each contained 75 identities absent from page one. Those numbers
are separate comparisons with page one, not a claim that every returned item is
mutually distinct, complete or usable.

**Decision:** use aliases, category selection and existing paging first. Keep
working behavior. A Knaben-first latency trial may be useful given APIBay's
small observed query contribution, but adding more general manga sources is not
currently supported by a measured unique target.

**Status (2026-10-04): alias retry and language presets implemented; ordering unchanged.**
- When the sources answer but no row matches the typed title, AniList's titles
  for the work are searched too. This costs one AniList request and searches at
  most two other names, and only applies when AniList lists the typed text as a
  title or synonym. A notice names the extra search.
- Live: `Yokohama Shopping Log` now returns 12 rows through `Yokohama Kaidashi
  Kikou` in about 8 seconds. `Attack on Titan` maps to `Shingeki no Kyojin`.
  `Twenty First Century Boys` has no AniList match and stays empty.
- Language presets (Portuguese, Spanish, French, Italian, Raw) rank or require
  tagged names. Each searches the matching Nyaa category (Non-English or Raw)
  even when that engine is saved Off.
- A language typed after the title (`Berserk português`) applies its preset to
  that search and also searches the title alone. A notice says how many results
  carry the tag. Live, Nyaa's Non-English Berserk releases were Italian,
  Spanish, French and Arabic, and none was Portuguese; the notice says so.
- Result ordering is otherwise unchanged (seeders first), as is paging.
- Spelled-out numbers (added later the same day, for every provider): when
  nothing matches, the digit spelling is searched too. No catalog listed
  `Twenty First Century Boys` or `Mob Psycho Hundred` (AniList, MangaDex,
  MangaUpdates and Kitsu were compared on 16 alternate titles; Jikan's API was
  down), but Nyaa has both under digits. Live, they now return 6 and 12 rows. AniList
  resolved all 11 ordinary English/romaji swaps, so no catalog was added.

## Madokami

**Scope:** authenticated direct-download manga library. Search results can be
directories rather than individual chapter/volume files. This is not a torrent
index; the app's later direct-download path was not tested by the audit.

**Engine/default:** Madokami On, no alternative engine or app Load more operation.
Credentials were configured and live authenticated search worked. Candidates
appeared for **27/31** queries, with 27 result-bearing searches and five empties
including the negative. The selected repeat matched the initial row count.

**What worked:** the source found series directories, including One Piece, and
supported some native-name queries. It contributed results to combined Saki
search despite RuTracker's access failure.

**Limits:** One Piece's first result was the unrelated *Ohana Moyou no One-Piece*
directory; the intended One Piece directory was second. Other related titles or
aliases can appear. Chapter, volume, batch and language suffixes may not be
present on a directory name: requiring `c001` removed all sampled One Piece and
Berserk directory rows. Directory discovery does not establish chapter completeness.

**Decision:** preserve authenticated directory discovery and make the work/folder
distinction clear. Improve work disambiguation if needed; use directory browsing
for file-level questions. Do not treat every literal chapter-filter empty as a
broken source or automatically expand to unrelated catalogs.

**Status (2026-10-04): names, ranking and folder browsing implemented.**
- Rows are named from the library path rather than shown as the raw path:
  `One Piece [series folder]`, `One Piece › One Piece [Viz] [folder]`,
  `Berserk › Berserk v01.cbz [file]`. Areas outside the main index are named:
  `[Raws · series folder]`, `[Doujinshi · …]`, `[Oneshots · …]`, `[Novels · …]`.
- The series named exactly as searched, and everything inside it, ranks first.
  Spin-offs and other areas follow, then titles merely containing the words.
  Matches found only through other names or authors (One Piece finding *Soft
  Shell*) come last but stay listed. Replaying the audit, *Ohana Moyou no
  One-Piece* drops from first place to below every One Piece row.
- A picked series folder used to end at "No files at this level" when it held
  only release folders, as One Piece and Yokohama Kaidashi Kikou do. Folders now
  open in place: step into a release folder, pick its files, and Esc goes up one
  level. Each folder is listed at most once per pick.
- Folder listings carry file sizes into the picker. The listing's "Back" link
  is no longer offered as a sub-folder.
- A title matching nothing is retried under AniList's names, like General
  Manga. Live, `Yokohama Shopping Log` (empty in the audit) now finds the
  `Yokohama Kaidashi Kikou` series folder. A combined search with General
  Manga makes one AniList request for both.

## Books

**Scope:** book/ebook listings, with some audiobook queries. Libgen contributes
direct-download listings; the other engines contribute torrent listings. The
sample included classics, recent fiction, technical books, Portuguese titles,
other languages and format variants.

| Engine | Default | Queries with a title candidate |
|---|---|---:|
| Libgen | On | 25 |
| APIBay | On | 8 |
| Knaben | Auto | 19 |
| SolidTorrents | Off | 3 observed; 29 cells skipped |

**What worked:** defaults supplied candidates for **28/31** queries; observed
all-On responses raised this to **29/31**. Libgen's selected repeat was stable.
Portuguese classics such as Dom Casmurro and the sampled Brás Cubas titles
returned candidates. Knaben exposes Load more; its Dune book pages two and three
were empty in the selected check.

**Confirmed relevance/fallback tradeoff:** Libgen returned other works for
`Tomorrow and Tomorrow and Tomorrow`, including Thomas Sweterlitsch's *Tomorrow
and Tomorrow*. Because primary engines had raw rows, Knaben Auto was skipped.
An independent Knaben search put Gabrielle Zevin's requested novel first.
Switching Knaben On recovered that title in replay.

The first five Libgen rows for *Pride and Prejudice* were derivatives/variations
rather than Austen's original. Title-word matches are therefore an optimistic
proxy for the intended book. Initial Libgen searches also had four timeouts;
APIBay had five. Their healthy and failed results are recorded separately.

**Decision:** improve work/author relevance and evaluate the raw-row Auto rule
carefully. A manual search with Knaben On is already a workaround. This is an
intentional fallback tradeoff, not a newly introduced regression; preserve
approximate matches and useful editions while improving ranking.

**Status (2026-10-04): implemented for Books only.**
- `book_title_score` reads "Title — Author", "Author - Title", "Title by Author"
  and "A / B" names. It compares word counts, allows author words in the query,
  and ignores format words ("epub", "audiobook").
- Books rank by it, and Libgen still leads among equally good matches. Nothing
  is filtered out.
- Knaben (Auto) now also runs when the On engines returned rows but none
  matches the title.
- Replaying the audit's rows: Austen's original editions now lead "Pride and
  Prejudice", ahead of "Variation" spin-offs. For "Tomorrow and Tomorrow and
  Tomorrow", Libgen's 16 rows score 0 and Apibay was empty, so Knaben runs, and
  its first row is Zevin's novel.
- Known limits: same-title different books ("The Name of the Rosé") and works
  named after the original can tie with it. Other providers keep the raw-row
  Auto rule.

**Status (2026-10-04): author-aware ranking (P13).**
- When the requested work's author is known, an exact title by that author
  ranks first. Libgen entries whose author field names a clearly different
  author drop below exact titles with an unknown author.
- Torrent names only gain from a match. Other scripts and missing authors stay
  neutral.
- Authors come from Search by Creator, Identify title, words typed in the query,
  or a parallel Open Library title lookup. The lookup counts only a clearly
  dominant work: at least 10 editions and 3× any same-title work by others.
- A live calibration returned Kafka, Stoker, Austen, Tolkien, Shelley, Frank
  Herbert and Zevin, and nothing for "The Name of the Rose" (Eco's work is
  catalogued under its Italian title).
- Replaying with authors puts Eco's listings above Christine Blum's "The Name of
  the Rosé" and Shelley's editions above the Junji Ito Frankenstein collection.

**Optional catalogs:** Gutenberg supplied verified originals for five sampled
works already observed through existing searches, plus a German Metamorphosis
route missed by `Die Verwandlung`. It is useful for a clean classics/language
route, but not necessary for general title breadth. Four Internet Archive probes
showed overlap, noisy/derivative matches and access restrictions; the measured
incremental value does not justify prioritizing a general integration.

## Shared engine maintenance and implementation priorities

**APIBay:** its 224 initial cells generated 1,292 HTTP observations through
requests/retries/fallbacks. This supports testing source order in Software,
Mobile and Manga, not removing the engine. Audit latency includes deliberate
pacing and must not be sold as normal UI performance.

**SolidTorrents:** across its 192 initial provider cells, 12 returned results,
two timed out, one hit a rate limit and 177 were skipped. A later Matrix control
worked again. Keep it optional, honor cooldown/Retry-After, and do not grade its
unknown cells as misses. Its configured endpoint redirected through BitSearch.
**Status (2026-10-04):** an HTTP 429 now pauses SolidTorrents for every
provider for its `Retry-After` (seconds or date; 60 s when absent, at most 15
minutes). During the pause it is not asked again, and the search says when it
will be.

**Knaben:** fourteen v2 requests over seven queries succeeded. It is the same
meta-index, with substantial overlap, not a new catalog. Its new defaults exclude
zero-seed rows unless requested: Blender returned one without `dead` versus
eleven with it; Dune Books returned nine versus 24. Evaluate migration with
category, hash, paging, safety and zero-seed compatibility checks. No migration
deadline or current v1 outage was established.
**Status (2026-10-04): migrated to v2.** Knaben's v2 page says the server
struggled to serve API bandwidth, and that GET searches let its edge server
cache work that v1's POST bodies could not. A live comparison of v1 and v2 on
12 query/page pairs matched in every pair: totals, info-hash sets, order,
zero-seed rows, hash-less rows and all-words title matching (Blender, Dune Part
Two, One Piece, Dune books, Stardew Valley, Adobe Photoshop; two pages each).
The client sends `sf=title`, seeders descending, 50 a page and the `dead` flag,
so zero-seed rows stay visible as before. v2's defaults keep unsafe and XXX
rows hidden. Uncached v2 calls were about 0.25 s slower; repeat calls were
served from the edge in about 0.1 s.

**Final review ranking fixes (2026-10-04).** A review replaying the audit's rows
found and fixed these:
- Numbers in the searched title stopped being treated as years or episodes.
  `Cyberpunk 2077`'s 47 rows had all scored 0; `1984` now ranks Orwell's book
  first instead of journal issues. Of several bare years only the last is the
  release year, so `Blade Runner 2049 (2017)` ranks below the original.
- Books' Auto rule now needs the requested book itself (score 3), so another
  author's `The Name of the Rosé` or `1984` journals no longer keep Knaben
  from running.
- Movies score each title of `Матрица / The Matrix [...]` listings.
- Release tags typed after an Anime/general title no longer zero every row
  (`Saki 720p`).
- Desktop/Mobile rank listings that start with the name (`Minecraft Pocket
  Edition`, `VLC Media Player`) above add-ons and look-alikes. `7-Zip` no
  longer matches every `.zip` with a 7 in its version. Mobile's Auto rule
  counts those listings as answers.
- Raw manga with kanji-only names or `[JP]` tags count for the Raw preset, and
  `[DUAL JAP PT-BR]` counts as Brazilian audio.
- Mobile/Desktop platform filters keep programs about the other platform
  (`Android Studio … Windows`, `[Android + iOS]`).
- Author matching accepts either name order and ignores "Jr.".

Suggested order, subject to a subsequent implementation request:

1. **Needed:** Online-Fix error/result parsing and shared pacing; clearer blocked
   access/rate-limit diagnostics, with bounded retries and partial results.
2. **Worth improving:** Online-Fix known-title discovery and Books/work relevance
   plus the Auto-fallback tradeoff.
3. **Maintenance evaluation:** Knaben v2 compatibility.
4. **Optional trials/addition:** Knaben-first for selected categories; F-Droid
   for the three demonstrated Android app gaps.
5. **Lower priority:** Gutenberg if a direct classics route is desired. Defer
   general Internet Archive and broad indexer additions without unique evidence.

## Evidence, sources and update guidance

Use [inventory.json](audits/2026-10-03/inventory.json) for exact factory modes and
category IDs, [engine-results.csv](audits/2026-10-03/engine-results.csv) for engine
counts/timings, [cases.json](audits/2026-10-03/cases.json) for all query strings,
and [manual-relevance.json](audits/2026-10-03/manual-relevance.json) for the 88
targeted listing judgments. The full report links all raw archives and explains
uncertainty. The manual sample deliberately includes 50 misleading Knaben Saki
rows; its error rate must not be extrapolated to all searches.

Candidate-source documentation consulted during the audit:
[F-Droid APIs](https://f-droid.org/docs/All_our_APIs/),
[Gutenberg metadata catalogs](https://www.gutenberg.org/ebooks/offline_catalogs.html),
[Internet Archive developer documentation](https://archive.org/developers/), and
[Knaben v2](https://knaben.org/api/v2/).

Future changes should update the affected provider section with the new version,
test date and supporting evidence. Preserve the historical audit rather than
silently rewriting an old observation as though it described new behavior.
