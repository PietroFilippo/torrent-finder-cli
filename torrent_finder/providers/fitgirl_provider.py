"""FitGirl provider — anonymous search of fitgirl-repacks.site (HTML scrape).

The official source for FitGirl's game repacks. No login anywhere — search
scrapes the public WordPress listing, and repack posts carry public magnets, so
selections feed the normal magnet pipeline. Results carry the post id as a
placeholder ``info_hash``; main.py resolves the real magnet from the post page
when a result is selected (see fitgirl.resolve_info_hash), same shape as the
RuTracker lazy resolve.
"""

from torrent_finder import fitgirl
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.search_result import SearchResult


class FitGirlProvider(BaseProvider):
    name = "FitGirl"
    slug = "fitgirl"
    icon = "🧚"
    categories = []  # not Apibay-based; the engine talks to fitgirl-repacks.site directly
    search_note = "Repacks from the official fitgirl-repacks.site — no account needed; the magnet resolves from the post when you pick one."

    # Game installers — none of the video-centric features apply.
    supports_subtitles = False
    supports_streaming = False
    supports_episode_picker = False

    def _init_engines(self) -> list[SearchEngine]:
        return [SearchEngine("FitGirl", "🧚", self._search_fitgirl, enabled=True)]

    def _search_fitgirl(self, query: str) -> list[SearchResult]:
        return fitgirl.search(query)
