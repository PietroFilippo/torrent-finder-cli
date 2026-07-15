# ADR-0004: Provider registry drives CLI choices

Status: accepted (2026-07-15)

## Context

The provider registry already owned provider identity and creator-search
facets, but `main.py` repeated both as hardcoded argparse choice lists. The
interactive tips repeated the provider list again. Adding a Provider or a new
creator facet could therefore leave direct CLI search unavailable or its help
stale until unrelated callers were edited.

The existing CLI used the singular names `movie` and `game`, while the
canonical Provider slugs are `movies` and `games`. Removing those spellings
would break documented commands.

## Decision

`providers/__init__.py` derives accepted `-t` names and `--by` facet keys from
the flat `PROVIDERS` registry. Every Provider slug is accepted automatically.
A Provider may declare `cli_aliases` for compatibility names; Movies and Games
declare `movie` and `game` respectively.

The registry validates that slugs and aliases do not collide. `main.py` and
the interactive CLI tip consume the derived choices and do not carry their
own provider or creator-facet lists.

## Consequences

- A newly registered Provider is immediately available through `-t <slug>`.
- A new `creator_facets` key is immediately accepted by `--by`.
- Existing `-t movie` and `-t game` commands continue to work, while the
  canonical `-t movies` and `-t games` forms are now accepted too.
- Provider display names remain presentation-only and never become CLI
  identity keys.
- Adding an alias that collides with another slug or alias fails during
  registry import instead of producing ambiguous dispatch.
