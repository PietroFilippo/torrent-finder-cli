"""Game torrent provider — searches PC game and console categories."""

# i18n: converted
from torrent_finder.filters import FilterConfig, FilterPreset
from torrent_finder.i18n import N_
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.search_result import SearchResult
from torrent_finder.resolvers import CreatorFacet, games


class GameProvider(BaseProvider):
    # Shown as "General" under the Games group; slug stays "games" so the -t flag
    # and existing history/stats keys keep working.
    name = N_("General")
    slug = "games"
    cli_aliases = ("game",)
    icon = "🎮"
    search_note = N_("PC, consoles, ROMs & repacks from public trackers and specialist sources.")
    broad = True  # also searches FitGirl and Online-Fix, which have their own providers
    categories = [400, 401, 403, 404, 405, 406]  # All, PC, PSX, Xbox, Wii, Handheld
    # APIBay's unscoped query cache can return false empty sentinels. Retry
    # once with all game categories in a single comma-separated request.
    apibay_fallback_categories = tuple(categories)
    knaben_categories = (4_000_000, 7_000_000)  # PC + Console
    solidtorrents_category = "Game"  # i18n: ignore — service/engine identity, including external category values

    default_filters = FilterConfig(exclude_keywords=["update only", "update v"])  # i18n: ignore — literal service or release-name match data
    presets = [
        FilterPreset(N_("Repacks Only"), FilterConfig(include_keywords=["fitgirl", "dodi", "kaos"])),
        FilterPreset(N_("Scene"), FilterConfig(include_keywords=["plaza", "rune"])),
        FilterPreset(N_("ROM Only"), FilterConfig(include_keywords=["rom", "nds", "gba", "3ds", "nsp", "xci", "pkg", "wbfs"])),
        FilterPreset(N_("PC Only"), FilterConfig(exclude_keywords=["rom", "nds", "gba", "3ds", "nsp", "xci", "pkg", "wbfs", "wii", "ps3", "ps4", "xbox"])),
        FilterPreset(N_("GOG"), FilterConfig(include_keywords=["gog"])),
        FilterPreset(N_("Online Fix"), FilterConfig(include_keywords=["online-fix", "onlinefix"])),
        FilterPreset(N_("Trusted Uploaders"), FilterConfig(include_keywords=[
            "fitgirl", "dodi", "kaos", "empress", "razor1911",
            "plaza", "codex", "rune", "tenoke", "skidrow",
        ])),
    ]

    # Search by creator. Always available: keyless Wikidata fallback by default,
    # richer IGDB data when Twitch creds are configured (see resolvers/games.py).
    # Developer and publisher are separate facets (a company can be both).
    creator_facets = [
        CreatorFacet(
            key="developer", label=N_("Developer"), icon="🎮",
            search_entities=games.developer_search,
            list_works=games.developer_works,
            note=N_("Find a developer's games, then search each title. "
                 "Add IGDB creds (Credentials) for richer results."),
        ),
        CreatorFacet(
            key="publisher", label=N_("Publisher"), icon="🏢",
            search_entities=games.publisher_search,
            list_works=games.publisher_works,
            note=N_("Find a publisher's games, then search each title. "
                 "Add IGDB creds (Credentials) for richer results."),
        ),
    ]

    def _init_engines(self) -> list[SearchEngine]:
        """Public trackers + Online-Fix + FitGirl. The site engines are folded in
        as toggleable engines (both search anonymously) so they're included in
        both keyword and by-developer/publisher searches; the standalone
        providers stay for focused searches. Picked results are routed by the
        results loop on their ``source`` (Online-Fix → .torrent handoff,
        FitGirl → lazy magnet resolve)."""
        return [
            SearchEngine("Apibay", "🏴‍☠️", self._search_apibay, enabled=True),  # i18n: ignore — service/engine identity, including external category values
            SearchEngine("Online-Fix", "🔧", self._search_online_fix, enabled=True,
                         empty_hint=self._online_fix_hint),
            SearchEngine("FitGirl", "🧚", self._search_fitgirl, enabled=True),  # i18n: ignore — service/engine identity, including external category values
            SearchEngine(
                "Knaben", "🧭", self._search_knaben,  # i18n: ignore — service/engine identity, including external category values
                enabled=True, emergency_fallback=True,
            ),
            SearchEngine(
                "SolidTorrents", "🔗", self._search_solidtorrents,  # i18n: ignore — service/engine identity, including external category values
                enabled=False,
            ),
        ]

    def _online_fix_hint(self, query: str) -> str:
        from torrent_finder import online_fix
        return online_fix.empty_search_hint(query)

    def _search_online_fix(self, query: str) -> list[SearchResult]:
        """Anonymous online-fix.me search (same backend as the standalone provider)."""
        from torrent_finder import online_fix
        return online_fix.search(query)

    def _search_fitgirl(self, query: str) -> list[SearchResult]:
        """Anonymous fitgirl-repacks.site search (same backend as the standalone provider)."""
        from torrent_finder import fitgirl
        return fitgirl.search(query)
