"""Provider registry - import and expose all available providers."""

from providers.anime_provider import AnimeProvider
from providers.game_provider import GameProvider
from providers.manga_provider import MangaProvider
from providers.mobile_provider import MobileProvider
from providers.movie_provider import MovieProvider
from providers.rutracker_provider import RuTrackerProvider
from providers.software_provider import SoftwareProvider

# Registry of all available providers (order = display order)
PROVIDERS: list = [
    MovieProvider(),
    GameProvider(),
    SoftwareProvider(),
    MobileProvider(),
    RuTrackerProvider(),
    AnimeProvider(),
    MangaProvider(),
]


def get_provider(slug_or_prefix: str):
    """Look up a provider by slug (case-insensitive, allows prefix like 'movie' for 'movies').

    Used by the ``-t`` CLI flag and by the history menu to re-resolve a saved
    search. Match is on ``slug`` only — display ``name`` is no longer an
    identity key (see CONTEXT.md → "Provider").
    """
    needle = slug_or_prefix.lower()
    for p in PROVIDERS:
        if p.slug.lower().startswith(needle):
            return p
    return None


def get_provider_by_slug(slug: str):
    """Strict slug lookup. Returns None if no exact match."""
    for p in PROVIDERS:
        if p.slug == slug:
            return p
    return None


def display_name_for(slug: str) -> str:
    """Return the current display name for a provider slug, or the slug itself
    when unknown (orphaned history rows, removed providers)."""
    p = get_provider_by_slug(slug)
    return p.name if p else slug


def icon_for(slug: str) -> str:
    """Return the icon for a provider slug, or a generic fallback."""
    p = get_provider_by_slug(slug)
    return p.icon if p else "🔍"
