"""Filter system for structuring and applying search filters."""

from dataclasses import dataclass, field


@dataclass
class FilterConfig:
    include_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    min_seeds: int = 0
    quality: list[str] = field(default_factory=list)


@dataclass
class FilterPreset:
    name: str
    config: FilterConfig


def apply_filters(results: list[dict], config: FilterConfig) -> list[dict]:
    """Filter a list of torrent results based on the given FilterConfig."""
    if not config:
        return results

    filtered = []
    
    # Pre-process for case-insensitive matching
    includes = [k.lower() for k in config.include_keywords]
    excludes = [k.lower() for k in config.exclude_keywords]
    qualities = [q.lower() for q in config.quality]

    for r in results:
        name = r.get("name", "").lower()
        seeds = int(r.get("seeders", 0))

        if config.min_seeds > 0 and seeds < config.min_seeds:
            continue
            
        if excludes and any(ext in name for ext in excludes):
            continue
            
        # If includes is set, the name MUST contain at least one of the include keywords
        if includes and not any(inc in name for inc in includes):
            continue
            
        # If quality is set, the name MUST contain at least one of the quality keywords
        if qualities and not any(q in name for q in qualities):
            continue
            
        filtered.append(r)

    return filtered
