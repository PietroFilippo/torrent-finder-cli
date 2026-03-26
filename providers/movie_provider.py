"""Movie torrent provider — searches video/movie categories."""

from filters import FilterConfig, FilterPreset
from providers.base import BaseProvider


class MovieProvider(BaseProvider):
    name = "Movies"
    icon = "🎬"
    categories = [201, 207]  # Movies, HD Movies

    presets = [
        FilterPreset("HD Only", FilterConfig(quality=["1080p", "bluray"])),
        FilterPreset("Small Size", FilterConfig(quality=["x265", "hevc"])),
    ]
