"""Software / programs torrent provider — Apibay + SolidTorrents.

Desktop software only for now (Windows / macOS / Linux). Mobile app categories
(iOS 305, Android 306) are intentionally parked — to add mobile support later,
put them in ``categories`` and drop the android/ios excludes in
``default_filters`` below.
"""

from torrent_finder.filters import FilterConfig, FilterPreset
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.result_view import product_title_score


class SoftwareProvider(BaseProvider):
    # Shown as "Desktop" under the Software group; slug stays "software" so the
    # -t flag and existing history/stats keys keep working.
    name = "Desktop"
    slug = "software"
    # 💻 (laptop) is width-2 like the sibling icons; 🖥️ (desktop) is a
    # variation-selector emoji that Rich miscounts as width-1, so its menu row
    # overflows by a cell and wraps. Stick to clean width-2 emoji here.
    icon = "💻"
    search_note = "Desktop programs for Windows, macOS & Linux."
    # The Pirate Bay "Applications" categories: 300 Applications, 301 Windows,
    # 302 Mac, 303 UNIX/Linux, 399 Other OS. (Mobile parked: 305 iOS, 306 Android.)
    categories = [300, 301, 302, 303, 399]
    # Knaben PC subcategories: Software, Mac, Unix.
    knaben_categories = (4_002_000, 4_003_000, 4_004_000)
    solidtorrents_category = "Apps"

    # Software isn't video/audio — no streaming or subtitle features. Use the
    # Torrent info option to inspect a torrent's file list before downloading.
    supports_subtitles = False
    supports_streaming = False
    supports_episode_picker = False

    # SolidTorrents doesn't strictly honor the category param, so keep mobile
    # results out by keyword while this provider is desktop-only.
    default_filters = FilterConfig(exclude_keywords=["android", "ios", "apk"])

    presets = [
        FilterPreset("Pre-activated / Cracked", FilterConfig(include_keywords=[
            "pre-activated", "preactivated", "activated", "cracked", "crack", "repack",
        ])),
        FilterPreset("Portable", FilterConfig(include_keywords=["portable"])),
        FilterPreset("Windows", FilterConfig(include_keywords=["windows", "win64", "win32", "x64", "x86"])),
        FilterPreset("macOS", FilterConfig(include_keywords=["macos", "mac os", "osx", "dmg"],
                                          include_regex=r"\bmac\b")),  # "for Mac", "(MAC)"
        FilterPreset("Linux", FilterConfig(include_keywords=["linux", "ubuntu", "debian", "appimage"])),
    ]

    # The searched program before longer products containing its name
    # ("Photoshop 2024" before "Photoshop Lightroom Classic").
    prefer_title_matches = True
    # A platform typed after the name ("Photoshop mac") ranks that platform's
    # releases first for the search; the name alone is searched too.
    typed_presets = {
        "Windows": ("windows", "win", "win64", "win32"),
        "macOS": ("mac", "macos", "osx"),
        "Linux": ("linux",),
        "Portable": ("portable",),
    }

    def title_relevance(self, row, query: str, authors: tuple = ()) -> int:
        return product_title_score(row.name, self.typed_split(query)[0])

    def _init_engines(self) -> list[SearchEngine]:
        """APIBay and category-scoped Knaben on, SolidTorrents manually off.

        The 2026-10-03 audit: APIBay averaged 5.4 s and found rows for 8 of 32
        programs, Knaben 0.8 s and 26. Knaben runs alongside instead of after
        APIBay; APIBay stays on because its rows were mostly not in Knaben's.
        """
        return [
            SearchEngine("Apibay", "🏴‍☠️", self._search_apibay, enabled=True),
            SearchEngine(
                "Knaben", "🧭", self._search_knaben,
                enabled=True, emergency_fallback=True,
            ),
            SearchEngine(
                "SolidTorrents", "🔗", self._search_solidtorrents,
                enabled=False,
            ),
        ]
