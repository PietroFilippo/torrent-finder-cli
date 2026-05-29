"""Manga torrent provider — searches Nyaa Literature plus Apibay Comics."""

from filters import FilterConfig, FilterPreset
from providers.base import BaseProvider, SearchEngine


class MangaProvider(BaseProvider):
    name = "Manga"
    slug = "manga"
    icon = "📚"
    categories = [602]  # Apibay/TPB Comics
    nyaa_category = "3_1"  # Literature - English-translated (default Nyaa engine)

    supports_subtitles = False
    supports_episode_picker = True  # volume/chapter batches → aria2 file-selection

    presets = [
        FilterPreset("Complete / Full", FilterConfig(include_keywords=["complete", "full series"])),
        FilterPreset("By Volume", FilterConfig(include_keywords=["volume", "vol."])),
        FilterPreset("Color", FilterConfig(include_keywords=["color", "colour"])),
        FilterPreset("Official / Digital", FilterConfig(include_keywords=["official", "digital"])),
        FilterPreset("Official Publishers", FilterConfig(include_keywords=[
            "viz", "kodansha", "yen press", "seven seas", "square enix", "j-novel",
        ])),
        FilterPreset("Exclude Light Novels", FilterConfig(exclude_keywords=["light novel"])),
    ]

    def _init_engines(self) -> list[SearchEngine]:
        """Nyaa Literature (English) + Apibay Comics on by default; Raw Nyaa off."""
        return [
            SearchEngine("Nyaa (EN)", "🍙", self._search_nyaa, enabled=True),
            SearchEngine("Nyaa (Raw)", "🗾", self._search_nyaa_raw, enabled=False),
            SearchEngine("Apibay", "🏴‍☠️", self._search_apibay, enabled=True),
        ]

    def _search_nyaa_raw(self, query: str) -> list[dict]:
        """Nyaa Literature - Raw (Japanese), c=3_2. Off by default."""
        return self._search_nyaa_in(query, "3_2")
