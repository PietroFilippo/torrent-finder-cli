# ADR-0001: Provider slug is the identity key

Status: accepted (retroactive — decision predates this record)

## Context

Providers originally persisted under their display `name` ("Movies",
"Games"). Renaming a provider for the UI ("Movies" → "Movies & Series")
silently orphaned its saved engine toggles, history entries, and stats
counters. Display names also collide: the game and manga verticals both want
a "General" entry inside their groups.

## Decision

Every provider carries an immutable lowercase `slug` distinct from its
display `name`. All identity resolution — persistence keys in
`filter_state.json` (providers/history/stats subtrees), the `-t` CLI flag,
`get_provider*` lookups — uses `slug` only. `name` and `icon` are free to
change at any time.

Legacy files keyed on display names are migrated once at load
(`state._migrate_legacy_names`), idempotently; stats counters for merged keys
are summed.

## Consequences

- Renames and display regrouping (ProviderGroup) are free; identity never
  moves.
- Duplicate display names are allowed (two "General" providers in different
  groups).
- A new provider must pick its slug once, correctly — changing it later means
  another migration entry.
- Orphaned rows (a removed provider's slug in history) render via
  `display_name_for`, which falls back to the slug itself.
