"""Software / programs torrent provider — Apibay + SolidTorrents.

Desktop software only for now (Windows / macOS / Linux). Mobile app categories
(iOS 305, Android 306) are intentionally parked — to add mobile support later,
put them in ``categories`` and drop the android/ios excludes in
``default_filters`` below.
"""

from filters import FilterConfig, FilterPreset
from providers.base import BaseProvider, SearchEngine


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
        FilterPreset("macOS", FilterConfig(include_keywords=["macos", "mac os", "osx", "dmg"])),
        FilterPreset("Linux", FilterConfig(include_keywords=["linux", "ubuntu", "debian", "appimage"])),
    ]

    def _init_engines(self) -> list[SearchEngine]:
        """Apibay on by default; SolidTorrents off — its software results are
        noisier (crack-site reposts), so make it opt-in for this provider."""
        return [
            SearchEngine("Apibay", "🏴‍☠️", self._search_apibay, enabled=True),
            SearchEngine("SolidTorrents", "🔗", self._search_solidtorrents, enabled=False),
        ]
