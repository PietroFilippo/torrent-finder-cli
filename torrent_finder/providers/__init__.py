"""Provider registry - import and expose all available providers."""

from dataclasses import dataclass, field

from torrent_finder.providers.base import BaseProvider
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.book_provider import BookProvider
from torrent_finder.providers.fitgirl_provider import FitGirlProvider
from torrent_finder.providers.game_provider import GameProvider
from torrent_finder.providers.madokami_provider import MadokamiProvider
from torrent_finder.providers.manga_provider import MangaProvider
from torrent_finder.providers.mobile_provider import MobileProvider
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.providers.online_fix_provider import OnlineFixProvider
from torrent_finder.providers.rutracker_provider import RuTrackerProvider
from torrent_finder.providers.software_provider import SoftwareProvider

# Singleton provider instances. Named so the display menu can nest some of them
# under a group without changing the flat registry below.
_movie = MovieProvider()
_game = GameProvider()
_online_fix = OnlineFixProvider()
_fitgirl = FitGirlProvider()
_desktop = SoftwareProvider()
_mobile = MobileProvider()
_rutracker = RuTrackerProvider()
_anime = AnimeProvider()
_manga = MangaProvider()
_madokami = MadokamiProvider()
_books = BookProvider()

# Flat registry of every provider. This is the source of truth for identity:
# slugs (-t flag, history, stats, settings) all resolve against this list, so a
# provider stays reachable here even when the UI tucks it inside a group.
PROVIDERS: list[BaseProvider] = [
    _movie,
    _game,
    _online_fix,
    _fitgirl,
    _desktop,
    _mobile,
    _rutracker,
    _anime,
    _manga,
    _madokami,
    _books,
]


def _provider_names(provider: BaseProvider) -> tuple[str, ...]:
    """Accepted CLI identities for a provider, in help-display order."""
    return (*provider.cli_aliases, provider.slug)


def _build_provider_name_index() -> dict[str, BaseProvider]:
    index: dict[str, BaseProvider] = {}
    for provider in PROVIDERS:
        for raw_name in _provider_names(provider):
            name = raw_name.casefold()
            if name in index:
                other = index[name]
                raise ValueError(
                    f"Duplicate provider CLI name {raw_name!r}: "
                    f"{other.slug!r} and {provider.slug!r}"
                )
            index[name] = provider
    return index


_PROVIDERS_BY_CLI_NAME = _build_provider_name_index()


def provider_cli_choices() -> tuple[str, ...]:
    """Return every accepted -t value, derived from the registry."""
    return tuple(
        name
        for provider in PROVIDERS
        for name in _provider_names(provider)
    )


def creator_facet_choices() -> tuple[str, ...]:
    """Return unique --by facet keys in provider registry order."""
    return tuple(dict.fromkeys(
        facet.key
        for provider in PROVIDERS
        for facet in provider.creator_facets
    ))


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


# The "Games" umbrella collects the game sources. Picking it drills into General
# (public-tracker search) / Online-Fix (co-op cracks) / FitGirl (official repacks).
GAMES_GROUP = ProviderGroup(
    name="Games",
    icon="🎮",
    search_note="Games — General (public trackers), Online-Fix (co-op / online cracks), or FitGirl (official repacks).",
    children=[_game, _online_fix, _fitgirl],
)

# The "Software" umbrella collects the three app sources so they don't crowd the
# top-level list. Picking it drills into Desktop / Mobile / RuTracker.
SOFTWARE_GROUP = ProviderGroup(
    name="Software",
    icon="💿",
    search_note="Apps & programs — Desktop, Mobile (Android), or RuTracker.",
    children=[_desktop, _mobile, _rutracker],
)

# The "Manga" umbrella collects the manga sources. Picking it drills into
# General (public trackers) / Madokami (private library, direct downloads).
MANGA_GROUP = ProviderGroup(
    name="Manga",
    icon="📚",
    search_note="Manga — General (public trackers) or Madokami (private library, login needed).",
    children=[_manga, _madokami],
)

# Display order for the Select Provider screen (mixes standalone providers and
# groups). Distinct from PROVIDERS, which stays flat for identity lookups.
PROVIDER_MENU: list = [
    _movie,
    GAMES_GROUP,
    SOFTWARE_GROUP,
    _anime,
    MANGA_GROUP,
    _books,
]


def get_provider(slug_alias_or_prefix: str):
    """Look up a provider by slug, declared CLI alias, or unique prefix.

    Used by the -t CLI flag and by the history menu to re-resolve a saved
    search. Display name is never an identity key (see CONTEXT.md, Provider).
    """
    needle = slug_alias_or_prefix.casefold()
    exact = _PROVIDERS_BY_CLI_NAME.get(needle)
    if exact:
        return exact

    matches = []
    for name, provider in _PROVIDERS_BY_CLI_NAME.items():
        if name.startswith(needle) and provider not in matches:
            matches.append(provider)
    return matches[0] if len(matches) == 1 else None


def get_provider_by_slug(slug: str):
    """Strict slug lookup. Returns None if no exact match."""
    provider = _PROVIDERS_BY_CLI_NAME.get(slug.casefold())
    if provider and provider.slug.casefold() == slug.casefold():
        return provider
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


def group_for(provider) -> "ProviderGroup | None":
    """Return the display ProviderGroup that contains this provider, or None.

    Lets back-navigation from a group child (Online-Fix, FitGirl, Desktop,
    Mobile, RuTracker) return to the group's source submenu instead of the top
    list.
    """
    for item in PROVIDER_MENU:
        if isinstance(item, ProviderGroup) and provider in item.children:
            return item
    return None
