"""Game torrent provider — searches PC game and console categories."""

from filters import FilterConfig, FilterPreset
from providers.base import BaseProvider


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
