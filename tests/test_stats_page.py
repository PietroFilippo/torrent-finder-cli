"""Usage stats: bars, the download menu's names for methods, the header summary."""

import io
import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from rich.console import Console
from rich.text import Text

from torrent_finder.ui import selector, stats as stats_ui, theme


class StatsPageTests(unittest.TestCase):
    def items(self, stats):
        screen = Console(file=io.StringIO(), width=80, height=24, color_system=None)
        with patch.object(stats_ui, "console", screen), patch.object(stats_ui, "average_seeders", return_value=0):
            return stats_ui._build_items(stats)

    def test_methods_use_the_menu_names_and_say_how_they_ended(self):
        items = self.items({"method_picks": {"open_magnet": 29, "aria": 6, "stream_webtorrent": 2},
                            "method_completed": {"aria": 5}})
        rows = {item.label: item.hint.plain for item in items if item.value == "metric"}
        self.assertNotIn("open_magnet", rows)
        self.assertIn("handed to the client", rows["Open in client"])
        self.assertTrue(rows["aria2c download"].endswith("6  5 done · 83%"))
        self.assertTrue(rows["Stream · webtorrent"].endswith("started"))
        labels = [item.label for item in items]
        self.assertLess(labels.index("Open in client"), labels.index("aria2c download"))  # most used first

    def test_bars_scale_to_the_largest_in_their_section(self):
        items = self.items({"searches_by_provider": {"movies": 64, "anime": 32, "books": 1}})
        bars = {item.label: item.hint.plain.count(theme.BAR) for item in items if item.value == "metric"
                and theme.BAR in item.hint.plain}
        self.assertEqual(bars["Anime"] * 2, bars["Movies & Series"])
        self.assertEqual(bars["Books"], 1)  # never an empty bar for a count above zero
        hint = next(item.hint for item in items if item.label == "Anime")
        self.assertEqual(str(next(s.style for s in hint.spans if hint.plain[s.start:s.end].startswith(theme.BAR))),
                         theme.DEEP)

    def test_rows_with_bars_stay_inline_at_eighty_columns(self):
        items = self.items({"method_picks": {"aria": 600}, "method_completed": {"aria": 599},
                            "top_queries": {"a very long query that someone searched": 12}})
        screen = Console(file=io.StringIO(), width=80, height=24, color_system=None)
        with patch.object(selector, "console", screen):
            self.assertTrue(all(selector._inline_hint(item) for item in items if item.value == "metric"))

    def test_the_header_holds_first_use_sessions_and_runtime(self):
        status = stats_ui.header_status({"first_use": "2026-06-11T10:00:00+00:00", "session_count": 41,
                                         "total_runtime_s": 6 * 3600 + 12 * 60})
        self.assertEqual(status, "since 2026-06-11 · 41 sessions · 6h 12m")
        self.assertEqual(stats_ui.header_status({"session_count": 1}), "1 session · 0s")

    def test_figures_read_as_values_not_keys(self):
        items = self.items({"searches_total": 5})
        searches = next(item for item in items if item.label == "Searches")
        hint = selector._hint_text(searches)
        self.assertNotIn(theme.KEY, [str(span.style) for span in hint.spans])
        self.assertEqual(str(selector._hint_text(selector.SelectItem("Row", hint="7")).style), theme.MUTED)
        self.assertEqual(str(selector._hint_text(selector.SelectItem("Row", hint="U")).style), theme.KEY)
        self.assertIsInstance(searches.hint, Text)


if __name__ == "__main__":
    unittest.main()
