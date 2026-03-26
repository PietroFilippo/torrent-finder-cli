"""Anime torrent provider — searches video and TV categories."""

from filters import FilterConfig, FilterPreset
from providers.base import BaseProvider


class AnimeProvider(BaseProvider):
    name = "Anime"
    icon = "🍙"
    categories = [201, 205, 207, 208]  # Movies, TV, HD Movies, HD TV

    presets = [
        FilterPreset("HD Quality", FilterConfig(quality=["1080p", "720p"])),
        FilterPreset("Dual Audio", FilterConfig(include_keywords=["dual audio"])),
        FilterPreset("Subbed", FilterConfig(include_keywords=["sub"])),
    ]
