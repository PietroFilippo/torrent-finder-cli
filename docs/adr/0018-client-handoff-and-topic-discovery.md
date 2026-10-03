# ADR-0018: Explicit client handoff and catalog topic discovery

Status: Accepted

## Context

Users need access to saved results outside a provider search, real torrent-client
state after a handoff, and discovery by interests that release filenames cannot
reliably establish. General menus also need an explicit provider scope when
opening search-specific actions.

## Decision

Share quick-action journeys between the main menu, What's Next, and the provider
prompt, keeping bookmarks inside Quick actions. Passing a provider binds
search-specific actions to it; otherwise the action first selects its scope.
Keep main-menu navigation explicit and give each What's Next option a distinct
shortcut. After download-menu actions, offer Continue or Back to the same torrent
session or batch selection without submitting again.

Add optional qBittorrent WebUI API v2 credentials through the existing registry.
Use the acquisition seam to prepare magnets and Online-Fix torrent metadata.
Direct file downloads do not become torrent-client jobs. Destination review
precedes submission and describes full-torrent behavior. Save paths refer to the
client machine; only existing categories are selectable. Duplicate hashes skip
submission without moving or modifying existing jobs. The API client owns its
cookie session, preserves TLS verification, rejects redirects, and never retries
an add automatically. Acknowledgement, observed client presence, and download
completion remain distinct. The progress UI reads timestamped client snapshots
and refreshes only on request. WebUI exposure and authentication settings are
never changed by this integration.

For topic discovery, use the catalog's own genre/tag/keyword/subject vocabulary.
The user selects the actual term after entering a phrase. AniList descriptions
help find terms such as Time Manipulation from "time travel"; a 60% tag relevance
threshold limits incidental matches. TMDB keeps movie and TV vocabularies
separate. IGDB combines genre, theme, mode and keyword criteria. Open Library
uses one subject per search. All selected criteria apply; errors never cause
criteria to be dropped. Unsupported software categories retain literal keyword
search without claiming purpose discovery.

Keep discovery to three user-requested pages, three chosen works and two names
per work. Review the exact release queries and effective providers before
searching. A combined profile is cloned and narrowed to compatible selected
providers; it is not rewritten. The existing SearchSession handles release
searches, filters, diagnostics, pagination and acquisition identity. Exact chosen
queries persist in history.

## Consequences and validation

Catalogs have different vocabularies and may classify works imperfectly. A genre
or game-mode label cannot establish torrent availability or multiplayer behavior.
English phrases generally match catalog vocabulary better than free-form
sentences. TMDB/IGDB require credentials; AniList/Open Library are keyless.

Deterministic tests exercise a local HTTP WebUI fixture with actual cookies and
requests, duplicate and destination behavior, pending/failed submissions,
payload identities, bounded discovery, conjunction of criteria, unsupported
categories, scope isolation, exact history replay and menu navigation. Real
Windows terminal checks cover narrow layouts and the complete user journeys.
Targeted live AniList/Open Library checks validate keyword viability separately
from those tests; no broad release-provider coverage audit is implied.
