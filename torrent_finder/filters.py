"""Filter system for structuring and applying search filters."""

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass
class FilterConfig:
    include_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    min_seeds: int = 0
    quality: list[str] = field(default_factory=list)
    # Optional regex alternative to include_keywords, matched against the same
    # haystack. Release names spell the same tag
    # many ways (pt-BR, PT.BR, PT_BR, "Brazilian Pt") and bare substrings are
    # too loose ("leg" matches "college", "nacional" matches "internacional").
    # When both are set a row passes if it matches EITHER.
    include_regex: str = ""
    # Match include_regex against an accent-stripped haystack too, so one
    # pattern covers "portugues" and "português".
    fold_accents: bool = False
    # Additional name-only check for context-sensitive tags (audio vs subs).
    name_predicate: Callable[[str], bool] | None = None


@dataclass
class FilterPreset:
    """A named filter, optionally with search-time behaviour.

    ``config`` alone only narrows rows the engines already returned. Language
    presets need more than that: the engines index Portuguese releases under
    Portuguese release names, so an English query may not return rows for the
    filter to keep. Two optional fields close that gap:

      - ``query_terms``: extra spellings to fan the query out over, e.g.
        ("dublado",) turns one "Toy Story" search into "Toy Story" plus
        "Toy Story dublado".
      - ``require_engines``: engines forced On for the duration of a search
        while this preset is active, by ``SearchEngine.name``. Engines the user
        left Off stay Off afterwards — this does not rewrite saved modes.
    """
    name: str
    config: FilterConfig
    query_terms: tuple[str, ...] = ()
    require_engines: tuple[str, ...] = ()
    description: str = ""


def strip_accents(text: str) -> str:
    """Return *text* with combining marks removed (português -> portugues)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


@lru_cache(maxsize=64)
def _compiled(pattern: str) -> "re.Pattern | None":
    """Compile a preset regex once; a bad pattern disables that test."""
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return None


def apply_filters(results: list, config: FilterConfig) -> list:
    """Filter a list of torrent results based on the given FilterConfig."""
    if not config:
        return results

    filtered = []

    # Pre-process for case-insensitive matching
    includes = [k.lower() for k in config.include_keywords]
    excludes = [k.lower() for k in config.exclude_keywords]
    qualities = [q.lower() for q in config.quality]
    include_pattern = _compiled(config.include_regex) if config.include_regex else None
    fold_accents = getattr(config, "fold_accents", False)

    for r in results:
        name = r.get("name", "").lower()
        # Keyword include/exclude also match the source, so e.g. the Games
        # "Repacks Only" preset ("fitgirl") keeps FitGirl-source rows whose
        # names are plain game titles (same for "Online Fix" vs Online-Fix).
        haystack = f"{name} {r.get('source', '').lower()}"
        seeds = int(r.get("seeders", 0))

        if config.min_seeds > 0 and seeds < config.min_seeds:
            continue

        if config.name_predicate and not config.name_predicate(name):
            continue

        if excludes and any(ext in haystack for ext in excludes):
            continue

        if includes or include_pattern:
            # The name MUST match at least one include keyword or the regex.
            matched = any(inc in haystack for inc in includes)
            if not matched and include_pattern:
                matched = bool(include_pattern.search(haystack))
                if not matched and fold_accents:
                    matched = bool(include_pattern.search(strip_accents(haystack)))
            if not matched:
                continue

        # If quality is set, the name MUST contain at least one of the quality keywords
        if qualities and not any(q in name for q in qualities):
            continue

        filtered.append(r)

    return filtered
