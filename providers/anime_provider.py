"""Anime torrent provider — searches Nyaa by default, with optional Apibay/SolidTorrents."""

from filters import FilterConfig, FilterPreset
from providers.base import BaseProvider, SearchEngine


class AnimeProvider(BaseProvider):
    name = "Anime"
    slug = "anime"
    icon = "🍙"
    categories = [201, 205, 207, 208]  # Movies, TV, HD Movies, HD TV
    solidtorrents_category = "Anime"
    nyaa_category = "1_2"  # Anime - English-translated

    supports_subtitles = True
    supports_episode_picker = True

    presets = [
        FilterPreset("720p", FilterConfig(quality=["720p"])),
        FilterPreset("1080p", FilterConfig(quality=["1080p"])),
        FilterPreset("4K", FilterConfig(quality=["2160p", "4k"])),
        FilterPreset("Dual Audio", FilterConfig(include_keywords=["dual audio"])),
        FilterPreset("Subbed", FilterConfig(include_keywords=["sub"])),
        FilterPreset("Batch", FilterConfig(include_keywords=["batch"])),
        FilterPreset("Trusted Uploaders", FilterConfig(include_keywords=[
            "subsplease", "erai-raws", "erai", "horriblesubs",
            "judas", "toonshub", "commie", "mtbb",
        ])),
    ]

    def _init_engines(self) -> list[SearchEngine]:
        """Nyaa enabled by default; Apibay and SolidTorrents available but off."""
        return [
            SearchEngine("Nyaa", "🍙", self._search_nyaa, enabled=True),
            SearchEngine("Apibay", "🏴‍☠️", self._search_apibay, enabled=False),
            SearchEngine("SolidTorrents", "🔗", self._search_solidtorrents, enabled=False),
        ]
