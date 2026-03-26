"""Game torrent provider — searches PC game categories."""

from filters import FilterConfig, FilterPreset
from providers.base import BaseProvider


class GameProvider(BaseProvider):
    name = "Games"
    icon = "🎮"
    categories = [400, 401]  # Games All, PC Games

    default_filters = FilterConfig(exclude_keywords=["update only", "update v"])
    presets = [
        FilterPreset("Repacks Only", FilterConfig(include_keywords=["fitgirl", "dodi", "kaos"])),
        FilterPreset("Scene", FilterConfig(include_keywords=["plaza", "rune"])),
    ]
