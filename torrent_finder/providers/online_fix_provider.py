"""Online-Fix provider — credentialed search of online-fix.me (login + scrape).

Games bundled with online / co-op cracks. Both search and download work without
an account: the post page is public and the file host is referer-gated, not
login-gated.

Results carry the post id as a placeholder ``info_hash`` — there is no public
magnet, so selecting a result downloads the ``.torrent`` (resolved from the post
page) and hands it to the system torrent client rather than building a magnet
(see ``online_fix.fetch_torrent_for`` and main.py's Online-Fix branch).
"""

from torrent_finder import online_fix
from torrent_finder.providers.base import BaseProvider, SearchEngine


class OnlineFixProvider(BaseProvider):
    name = "Online-Fix"
    slug = "online-fix"
    icon = "🔧"
    categories = []  # not Apibay-based; the engine talks to online-fix.me directly
    search_note = "Co-op / online game cracks from online-fix.me — no account needed; a pick downloads the .torrent and opens it in your torrent client."

    # Games behind a private tracker — no public swarm, so none of the video/
    # magnet-centric features apply.
    supports_subtitles = False
    supports_streaming = False
    supports_episode_picker = False

    def _init_engines(self) -> list[SearchEngine]:
        return [SearchEngine("Online-Fix", "🔧", self._search_online_fix, enabled=True)]

    def _search_online_fix(self, query: str) -> list[dict]:
        return online_fix.search(query)
