"""Mobile (Android) app torrent provider — Apibay.

Android only: The Pirate Bay category 306 (Android). iOS (305) is intentionally
left out — IPA torrents are sparse and sideloading is impractical — so this
provider advertises that it covers Android (APK / MOD / OBB) only via
``search_note``.
"""

from filters import FilterConfig, FilterPreset
from providers.base import BaseProvider, SearchEngine


class MobileProvider(BaseProvider):
    name = "Mobile"
    slug = "mobile"
    icon = "📱"
    categories = [306]  # The Pirate Bay "Android" (iOS 305 left out on purpose)
    solidtorrents_category = "Apps"
    search_note = "Mobile is Android-only (APK / MOD / OBB); iOS/IPA isn't covered."

    # Apps aren't video/audio — no streaming or subtitle features.
    supports_subtitles = False
    supports_streaming = False
    supports_episode_picker = False

    # Apibay is already scoped to Android; this keeps iOS out of any
    # SolidTorrents results too (it ignores the category param).
    default_filters = FilterConfig(exclude_keywords=["ios", "ipa"])

    presets = [
        FilterPreset("MOD / Patched", FilterConfig(include_keywords=[
            "mod", "modded", "patched", "premium", "unlocked", "pro",
        ])),
        FilterPreset("APK only", FilterConfig(include_keywords=["apk"])),
        FilterPreset("With OBB / Data", FilterConfig(include_keywords=["obb", "data"])),
        FilterPreset("Games", FilterConfig(include_keywords=["game"])),
        FilterPreset("Ad-Free", FilterConfig(include_keywords=["ad-free", "adfree", "no ads", "no-ads"])),
    ]

    def _init_engines(self) -> list[SearchEngine]:
        """Apibay on by default; SolidTorrents off (noisier, ignores category)."""
        return [
            SearchEngine("Apibay", "🏴‍☠️", self._search_apibay, enabled=True),
            SearchEngine("SolidTorrents", "🔗", self._search_solidtorrents, enabled=False),
        ]
