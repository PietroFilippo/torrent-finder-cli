# ADR-0030: Empty-search advice and credentialed engines

Status: accepted (2026-11-04). Amended after review, the same day: the
notices reach the screen. The results table composes them itself each time
it opens or a retry or load-more refreshes it: the caller's own context, which
of several typed titles found nothing (`result_view.missing_titles_note`) and
the search's `results.notices`; diagnostics (**n**) list them first. Callers no
longer pass notices in `note`, so creator, discovery and saved searches show
them too and a stale copy never returns. A seed minimum skips rows without
swarm statistics in solo searches too (`filters.NO_SWARM_SOURCES`, shared with
combined search), so it no longer removes Madokami rows from Manga › General.
Manga › General `defers_to` Madokami: a row both manga providers find is
credited to Madokami, and no other overlap changes (`broad` would also have
moved Manga behind Books). Madokami folders are ranked by the title without a
language typed after it. Shared Madokami results are kept per login, read
from the session that made the request.

## Context

A user searched Manga › General for *Naki no Ryuu* and got nothing. The series
was on Nyaa, but only as Japanese raws, and the Nyaa (Raw) engine is Off by
default. It was also on Madokami, a sibling provider the search never asked.
The empty screen gave no sign of either. Mobile's F-Droid engine, Off by
default, has the same problem, and so do the site providers whose category
General search covers more (FitGirl, Online-Fix, Madokami).

Games › General already folds its sites in as engines (Online-Fix, FitGirl),
and site adapters share one request between providers (`SharedResults`).
Madokami could not follow that pattern: it needs a login, and an On engine
without a login would fail on every manga search for users who have no
account.

## Decision

- `SearchEngine.off_hint` gives advice for an engine that was not searched:
  what it covers and how to add it, preferably for one search (a typed preset
  word such as `raw`). The session attaches it to the engine's Off diagnostic.
- `SearchEngine.available` reports whether an engine can search right now.
  An unavailable engine is treated as Off for that search: it is not
  contacted, it is not a failure, there is nothing to retry, and it is left out
  of `effective_engines` (the provider row and the search prompt).
- `BaseProvider.empty_advice` lists `(provider slug, advice)` pairs pointing at
  a sibling provider. Advice is left out when that provider was part of the
  same search.
- All of this advice, like the existing `empty_hint`, appears only when the
  whole search found nothing.
- Manga › General gains a Madokami engine, On by default and available only
  while a Madokami login is saved. Manga › Madokami stays for a focused
  search. `madokami.search` goes through `SharedResults`, so a search across
  both providers sends Madokami one request set, and each provider keeps its
  rows, as with FitGirl.

Advice is wired where it is useful: Manga's Nyaa (Raw), Nyaa (Non-English)
and Madokami engines, Mobile's F-Droid, and sibling advice from Madokami,
FitGirl and Online-Fix to their General search and from RuTracker to Desktop.
Desktop does not point to RuTracker, whose scripted login Cloudflare
currently blocks. Off engines that only add noise (SolidTorrents, YTS,
Anime's APIBay) get no advice: Knaben already covers their trackers.

## Consequences

- An empty search explains what was left out and how to include it, and lists
  only advice the user can act on.
- Users with a Madokami login find its library from Manga › General without
  switching providers. Users without one see no new failures.
- A new engine absent from saved state starts at its code default (ADR-0010),
  so existing Manga › General settings gain Madokami On.
- Raws are still not searched automatically. Making Nyaa (Raw) an Auto engine
  would show untranslated results to readers who asked for English. The advice
  leaves that choice to the user.
