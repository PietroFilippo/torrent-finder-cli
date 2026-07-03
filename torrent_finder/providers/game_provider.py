"""Game torrent provider — searches PC game and console categories."""

from torrent_finder.filters import FilterConfig, FilterPreset
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.resolvers import CreatorFacet, games


class GameProvider(BaseProvider):
    # Shown as "General" under the Games group; slug stays "games" so the -t flag
    # and existing history/stats keys keep working.
    name = "General"
    slug = "games"
    icon = "🎮"
    search_note = "PC, consoles, ROMs & repacks from public trackers (Apibay + SolidTorrents)."
    categories = [400, 401, 403, 404, 405, 406]  # All, PC, PSX, Xbox, Wii, Handheld
    solidtorrents_category = "Game"

    default_filters = FilterConfig(exclude_keywords=["update only", "update v"])
    presets = [
        FilterPreset("Repacks Only", FilterConfig(include_keywords=["fitgirl", "dodi", "kaos"])),
        FilterPreset("Scene", FilterConfig(include_keywords=["plaza", "rune"])),
        FilterPreset("ROM Only", FilterConfig(include_keywords=["rom", "nds", "gba", "3ds", "nsp", "xci", "pkg", "wbfs"])),
        FilterPreset("PC Only", FilterConfig(exclude_keywords=["rom", "nds", "gba", "3ds", "nsp", "xci", "pkg", "wbfs", "wii", "ps3", "ps4", "xbox"])),
        FilterPreset("GOG", FilterConfig(include_keywords=["gog"])),
        FilterPreset("Online Fix", FilterConfig(include_keywords=["online-fix", "onlinefix"])),
        FilterPreset("Trusted Uploaders", FilterConfig(include_keywords=[
            "fitgirl", "dodi", "kaos", "empress", "razor1911",
            "plaza", "codex", "rune", "tenoke", "skidrow",
        ])),
    ]

    # Search by creator. Always available: keyless Wikidata fallback by default,
    # richer IGDB data when Twitch creds are configured (see resolvers/games.py).
    # Developer and publisher are separate facets (a company can be both).
    creator_facets = [
        CreatorFacet(
            key="developer", label="Developer", icon="🎮",
            search_entities=games.developer_search,
            list_works=games.developer_works,
            note="Find a developer's games, then search each title. "
                 "Add IGDB creds (Credentials) for richer results.",
        ),
        CreatorFacet(
            key="publisher", label="Publisher", icon="🏢",
            search_entities=games.publisher_search,
            list_works=games.publisher_works,
            note="Find a publisher's games, then search each title. "
                 "Add IGDB creds (Credentials) for richer results.",
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
            SearchEngine("Apibay", "🏴‍☠️", self._search_apibay, enabled=True),
            SearchEngine("SolidTorrents", "🔗", self._search_solidtorrents, enabled=True),
            SearchEngine("Online-Fix", "🔧", self._search_online_fix, enabled=True),
            SearchEngine("FitGirl", "🧚", self._search_fitgirl, enabled=True),
        ]

    def _search_online_fix(self, query: str) -> list[dict]:
        """Anonymous online-fix.me search (same backend as the standalone provider)."""
        from torrent_finder import online_fix
        return online_fix.search(query)

    def _search_fitgirl(self, query: str) -> list[dict]:
        """Anonymous fitgirl-repacks.site search (same backend as the standalone provider)."""
        from torrent_finder import fitgirl
        return fitgirl.search(query)
