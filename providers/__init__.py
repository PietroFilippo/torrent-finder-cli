"""Provider registry - import and expose all available providers."""

from dataclasses import dataclass, field

from providers.anime_provider import AnimeProvider
from providers.game_provider import GameProvider
from providers.manga_provider import MangaProvider
from providers.mobile_provider import MobileProvider
from providers.movie_provider import MovieProvider
from providers.online_fix_provider import OnlineFixProvider
from providers.rutracker_provider import RuTrackerProvider
from providers.software_provider import SoftwareProvider

# Singleton provider instances. Named so the display menu can nest some of them
# under a group without changing the flat registry below.
_movie = MovieProvider()
_game = GameProvider()
_online_fix = OnlineFixProvider()
_desktop = SoftwareProvider()
_mobile = MobileProvider()
_rutracker = RuTrackerProvider()
_anime = AnimeProvider()
_manga = MangaProvider()

# Flat registry of every provider. This is the source of truth for identity:
# slugs (-t flag, history, stats, settings) all resolve against this list, so a
# provider stays reachable here even when the UI tucks it inside a group.
PROVIDERS: list = [
    _movie,
    _game,
    _online_fix,
    _desktop,
    _mobile,
    _rutracker,
    _anime,
    _manga,
]


@dataclass
class ProviderGroup:
    """A display-only grouping shown on the Select Provider screen.

    Selecting a group opens a submenu of its ``children`` (each a normal
    provider from ``PROVIDERS``), so it changes only the menu shape — slugs,
    the ``-t`` flag, history, and state are all unaffected.
    """
    name: str
    icon: str
    children: list = field(default_factory=list)
    search_note: str = ""  # one-liner shown as the row's description

    @property
    def label(self) -> str:
        return f"{self.icon} {self.name}"


# The "Software" umbrella collects the three app sources so they don't crowd the
# top-level list. Picking it drills into Desktop / Mobile / RuTracker.
SOFTWARE_GROUP = ProviderGroup(
    name="Software",
    icon="💿",
    search_note="Apps & programs — Desktop, Mobile (Android), or RuTracker.",
    children=[_desktop, _mobile, _rutracker],
)

# Display order for the Select Provider screen (mixes standalone providers and
# groups). Distinct from PROVIDERS, which stays flat for identity lookups.
PROVIDER_MENU: list = [
    _movie,
    _game,
    _online_fix,
    SOFTWARE_GROUP,
    _anime,
    _manga,
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
