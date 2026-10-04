# Named search profiles and explicit preset preferences

Status: Accepted (2026-10-02). Amended in v0.8.0: title relevance now leads in Movies &
Series, Anime, Books, Desktop, Mobile, Madokami and combined search; rows
carrying tags typed with the title come before preferred-preset matches.

## Context

Combined search stored one setup, so switching between Anime + Manga and a
single-category language search meant replacing the saved configuration. Preset
checkboxes also conflated wanting a resolution with excluding every other one.

## Decision

`search_profiles.ProfileLibrary` owns a versioned collection under
`settings.search_profiles`: stable IDs, unique names, an active ID, and copies
of combined-provider snapshots. A profile can select one or several providers.
Snapshots retain engine modes, required/preferred presets, shared name rules,
and result order. Solo provider settings remain separate.

When the collection is absent, the existing `combined_search` settings become
Default in memory. The first explicit save commits the collection and mirrors
the active snapshot into `combined_search` for older versions. Reading or
cancelling does not rewrite data. Invalid collection data is reported rather
than replaced with an empty collection. No credentials are stored in profiles.

The combined settings screen edits a library draft. Switching retains the
outgoing profile's draft; creating copies the current setup; renaming preserves
identity. Deleting asks for confirmation and keeps at least one profile.
Save commits the whole library; Esc discards every nested edit. History replay
uses a detached snapshot. An explicit save of that replay creates a new History
search profile rather than overwriting a named setup. CLI `--profile NAME`
implies `-t all`, and name matching ignores case. CLI overrides remain in memory
unless the user explicitly saves settings.

Preset rows cycle Off → Require → Prefer. `active_presets` continues to mean
Require, including old saved selections. `preferred_presets` adds a matching
score without excluding rows. Required filters always run first. Both kinds of
preset participate in the existing bounded query expansion and temporary engine
requirements; engine modes are never rewritten by a preset.

Recommended order keeps title relevance first where the provider already uses
it (Anime and combined search), then counts preferred matches, then keeps the
existing ordering. This prevents an incidental 1080p title match from displacing
an exact-title 720p release. The best preferred alias survives deduplication
within a provider. Combined rows keep the first originating provider's identity,
capabilities, and preference score. Multi-title/creator merging retains this
ranking and copies source rows before annotating provenance.

Explicit seed/date/name/size sorts override the recommended ranking, while
required filters continue to apply. A provider or named profile saves its
initial result order; the table's refinement menu affects the current view only.
The combined profile's overall order takes precedence over its children's solo
sort settings. Selection always refers to original result indexes.

## Consequences

Users can keep several independent configurations and choose a resolution
preference without losing older releases. Anime remains unrestricted by default.
Requiring PT-BR audio retains the same strict name checks; a separate preference
never turns absent language evidence into a match.

Preferences do not change the catalog or inspect actual media tracks. Several
required presets must all match, as before. Preferring a language can still add
bounded network requests. Downgrading retains required filters through the
legacy snapshot, but older versions do not implement preference ranking or
named-profile switching.
