"""Offline snapshots of renderer-owned text, including the required 137x36 size.

Run: python tests/capture_ui_render.py ui-render-owned-qps qps
Then: python scripts/ui_snapshots.py check ui-render-owned-qps
Pass a third argument (quiet) for Simple; citrinitas is the default.
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import isolation  # noqa: F401 — state, credentials and terminal profile are isolated
from scripts import ui_snapshots as snapshots
from torrent_finder.i18n import t
from torrent_finder.providers.combined_provider import EngineProgress, ProviderProgress, SearchProgress
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.ui import chrome, inspector, search_progress, selector, theme


def scenarios():
    provider = MovieProvider()

    def notes():
        items = [selector.SelectItem(palette.name, description=t(palette.note)) for palette in theme.THEMES.values()]
        items += [selector.SelectItem(design.name, description=t(design.note)) for design in theme.DESIGNS.values()]
        selector.arrow_select(items, title=t("Appearance"))

    def badges():
        chrome.announce(t("You search the stacks…"))
        chrome.announce(t("This shelf"))
        items = [selector.SelectItem(str(index), toggle_states=("On", "Auto", "Off")) for index in range(40)]
        items += [selector.SelectItem("1080p", toggle_states=("Off", "Require", "Prefer"), toggle_state="Prefer")]
        selector.arrow_select(items, title=t("Select"), multi=True)

    def details():
        items = [selector.SelectItem(t("Providers"), inspect=lambda: inspector.provider(provider)),
                 selector.SelectItem(t("Logins and keys"), inspect=inspector.credentials),
                 selector.SelectItem(t("Recent searches"), inspect=lambda: inspector.continue_search({
                     "queries": ["Fixture query"], "presets": ["With Subtitles"],
                     "search_profile": {"selected": ["anime"], "shared": {"include_keywords": ["1080p"]}}})),
                 selector.SelectItem(t("Appearance"), inspect=inspector.appearance_details)]
        # Each run captures the focused inspector, with a list at narrow widths.
        for cursor in range(len(items)):
            try:
                selector.arrow_select(items, title=t("Select"), start_index=cursor)
            except (KeyboardInterrupt, EOFError, snapshots._Cancel):
                pass

    def progress():
        state = SearchProgress(1, 3, 2, ("Anime",), (
            ProviderProgress("Anime", "running", 0, (EngineProgress("Nyaa", "searching"),)),
            ProviderProgress("Manga · General", "done", 2, (EngineProgress("Knaben", "results", 2),)),
            ProviderProgress("Books", "failed", 0, (EngineProgress("Libgen", "timeout"),))))
        with search_progress.ProgressScreen() as screen:
            screen.draw(search_progress.progress_frame(t("Select"), "", [], state, 2, ""))

    return [("renderer-badges", badges), ("renderer-inspector", details), ("renderer-notes", notes),
            ("renderer-keys", lambda: selector.show_keys(t("Select"), t("Enter select • Esc back"))),
            ("renderer-progress", progress)]


if __name__ == "__main__":
    appearance = sys.argv[3] if len(sys.argv) > 3 else "citrinitas"
    with patch.object(snapshots, "_scenarios", scenarios), \
            patch.object(snapshots, "SIZES", [(40, 12), (80, 24), (137, 36), (200, 50)]):
        snapshots.capture(sys.argv[1], appearance + ":lang=" + sys.argv[2])
