"""Online-Fix provider — credentialed search of online-fix.me (login + scrape).

Games bundled with online / co-op cracks. Searching is public (no login); a free
online-fix.me account is only needed to download, so ``search_note`` flags that
and points the user at the credentials menu.

Results carry the post id as a placeholder ``info_hash`` — there is no public
magnet, so selecting a result resolves the authenticated ``.torrent`` from the
post page instead of building a magnet (see ``online_fix.resolve_torrent`` and
main.py's Online-Fix branch). In-terminal download is a later phase.
"""

import online_fix
from providers.base import BaseProvider, SearchEngine


class OnlineFixProvider(BaseProvider):
    name = "Online-Fix"
    slug = "online-fix"
    icon = "🔧"
    categories = []  # not Apibay-based; the engine talks to online-fix.me directly
    search_note = "Co-op / online game cracks from online-fix.me. Search is open; downloading needs a free account (add it under the credentials menu)."

    # Games behind a private tracker — no public swarm, so none of the video/
    # magnet-centric features apply.
    supports_subtitles = False
    supports_streaming = False
    supports_episode_picker = False

    def _init_engines(self) -> list[SearchEngine]:
        return [SearchEngine("Online-Fix", "🔧", self._search_online_fix, enabled=True)]

    def _search_online_fix(self, query: str) -> list[dict]:
        return online_fix.search(query)
