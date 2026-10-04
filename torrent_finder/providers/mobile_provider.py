"""Mobile (Android) app provider — Knaben and Apibay, plus optional F-Droid.

Android only: Knaben's Android category and The Pirate Bay category 306
(Android). iOS (305) is intentionally left out — IPA torrents are sparse and
sideloading is impractical — so this provider advertises that it covers Android
(APK / MOD / OBB) only via ``search_note``. F-Droid (Off by default) adds the
official repository of free and open-source apps, downloaded directly.
"""

import re

from torrent_finder import fdroid
from torrent_finder.filters import FilterConfig, FilterPreset
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.result_view import product_title_score
from torrent_finder.search_result import SearchResult


class MobileProvider(BaseProvider):
    name = "Mobile"
    slug = "mobile"
    icon = "📱"
    categories = [306]  # The Pirate Bay "Android" (iOS 305 left out on purpose)
    knaben_categories = (8_001_000,)  # Mobile / Android
    solidtorrents_category = "Apps"
    search_note = "Mobile is Android-only (APK / MOD / OBB); iOS/IPA isn't covered."

    # Apps aren't video/audio — no streaming or subtitle features.
    supports_subtitles = False
    supports_streaming = False
    supports_episode_picker = False

    # Apibay is already scoped to Android; this keeps iOS out of any
    # SolidTorrents results too (it ignores the category param). Whole words
    # only: "Studios", "Radios" or "Kiosk" are not iOS.
    # Listings naming Android too ("[Android + iOS]", "... Premium APK") stay.
    default_filters = FilterConfig(name_predicate=lambda name: not re.search(r"\b(?:ios|ipa)\b", name, re.I)
                                   or bool(re.search(r"\b(?:android|apk)\b", name, re.I)))

    presets = [
        FilterPreset("MOD / Patched", FilterConfig(include_keywords=[
            "mod", "modded", "patched", "premium", "unlocked", "pro",
        ])),
        FilterPreset("APK only", FilterConfig(include_keywords=["apk"]), description=(
            "Names that say APK. Android-category listings are apps either way and many never say "
            "APK (none of the audit's Stardew Valley rows did), so Prefer is usually better than Require.")),
        FilterPreset("With OBB / Data", FilterConfig(include_keywords=["obb", "data"])),
        FilterPreset("Games", FilterConfig(include_keywords=["game"])),
        FilterPreset("Ad-Free", FilterConfig(include_keywords=["ad-free", "adfree", "no ads", "no-ads"])),
    ]

    # The searched app before others containing its name; F-Droid rows are
    # matched on the app name without its tagline.
    prefer_title_matches = True
    # Auto (APIBay) also runs when Knaben's rows are only other apps naming
    # this one ("Pixel Gun 3D (Pocket Minecraft Edition)", "Mod for Minecraft").
    auto_needs_relevant_rows = True
    relevant_title_score = 2
    # A tag typed after the name ("Minecraft obb") ranks those releases first
    # for the search; the name alone is searched too.
    typed_presets = {
        "APK only": ("apk",),
        "MOD / Patched": ("mod", "modded", "patched"),
        "With OBB / Data": ("obb",),
    }

    def title_relevance(self, row, query: str, authors: tuple = ()) -> int:
        return product_title_score(row.get("fd_app") or row.name, self.typed_split(query)[0])

    def _init_engines(self) -> list[SearchEngine]:
        """Android-scoped Knaben on, APIBay auto, SolidTorrents and F-Droid off.

        The 2026-10-03 audit: APIBay averaged 5.6 s and returned rows for one of
        32 Android queries (all also in Knaben's); Knaben averaged 1.0 s and
        returned rows for 21. APIBay remains the fallback.
        """
        return [
            SearchEngine(
                "Knaben", "🧭", self._search_knaben,
                enabled=True, emergency_fallback=True,
            ),
            SearchEngine(
                "Apibay", "🏴‍☠️", self._search_apibay,
                enabled=False, emergency_fallback=True,
            ),
            SearchEngine(
                "SolidTorrents", "🔗", self._search_solidtorrents,
                enabled=False,
            ),
            SearchEngine("F-Droid", "🤖", self._search_fdroid, enabled=False, description=(
                "F-Droid's official repository: free and open-source apps only (no commercial games). "
                "A pick downloads the current APK from f-droid.org; Android checks its signature on install.")),
        ]

    def _search_fdroid(self, query: str) -> list[SearchResult]:
        """Free and open-source apps from F-Droid's official repository.

        Release tags mean nothing there: "VLC apk" is left to the search for
        the name alone, which runs too (see expand_queries)."""
        return [] if self.typed_preset(query) else fdroid.search(query)
