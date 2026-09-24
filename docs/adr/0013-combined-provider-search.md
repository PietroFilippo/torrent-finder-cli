# Combined search with independent provider settings

Status: Accepted

## Context

Users want to search several content types together, such as Anime and Manga,
without repeating queries. Flattening their engines would lose category scopes,
provider defaults, Auto fallback rules, and presets that also expand queries or
require engines. Applying a video resolution filter to manga or books would
discard valid results. Reusing registry instances would also change solo searches.

## Decision

Register `CombinedProvider` as `all`, with a separate persisted settings profile.
It selects concrete providers and stores their engine modes and preset names.
New profiles copy solo settings except Anime resolution presets; explicit later
choices persist. Shared name include/exclude rules apply to all selected providers.
The settings UI edits a draft and commits once, so Cancel discards nested edits.

Each invocation copies the profile into fresh provider instances. Run at most
three provider/query jobs, sharing six engine slots across all queries and
expansions. Provider search logic still owns category scope, fallback, defaults,
and presets. A result predicate applies shared rules before aliases of a torrent
are collapsed within a provider. Torrent seed requirements do not apply to direct
downloads without swarm statistics. Cancellation stops queued engine calls;
already-running requests finish according to their existing timeouts.

Collect failures per provider while retaining successful results. Display compact
notices with a details browser in short terminals. Copy source rows before adding
provider/query provenance. Merge valid hex info hashes across providers; scope
placeholder IDs by source and URL/handle. The first matching provider in registry
order supplies the row and its capabilities; retain every matching provider/query
in metadata. Sort by title relevance and preserve provider order for ties.

Use each row's originating provider for capabilities and pick statistics.
Continue to route acquisition by source. Search history records a deep copy of
the combined profile; replay restores it in memory. CLI `--providers` similarly
overrides the current session without changing saved solo or combined settings.

## Consequences

Provider-specific features, including preset query expansion and credential
errors, work without duplicating search implementations. Settings remain separate
and mixed tables keep the appropriate streaming, subtitle, and direct-download
behavior. There is no forced 1080p default for Anime.

Engines with the same name in different providers may still make separate calls
because their category scopes differ. Site entries with unresolved hashes cannot
be merged with indexed torrents until their real identity is known; combined
search does not fetch every detail page just to discover that identity. Existing
engine adapters that silently return no rows still cannot distinguish an outage
from an empty search. Creator searches remain provider-specific in this version.
