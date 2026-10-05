"""The inspector pane of wide windows, and the main menu's row details."""

import io
import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirects saved settings before anything reads them
from isolation import isolate_store
from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from torrent_finder import state
from torrent_finder.ui import inspector, prompts, selector, theme
from torrent_finder.ui.selector import SelectItem


def frame(items, cursor, width, height, **kwargs) -> list[str]:
    screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
    with patch.object(selector, "console", screen):
        screen.print(selector._build_panel(items, cursor, "Menu", False, "Enter select • Esc back", **kwargs))
    return screen.file.getvalue().rstrip("\n").split("\n")


def menu() -> list[SelectItem]:
    return [SelectItem("Shelves", "section_header", enabled=False),
            SelectItem("Anime", "anime", hint="Nyaa", description="Anime from Nyaa.",
                       inspect=lambda: [Text("ENGINES"), Text("  Nyaa   On")]),
            SelectItem("Books", "books", hint="Libgen", description="Books from Libgen.")]


class PaneLayoutTests(unittest.TestCase):
    def test_wide_windows_show_the_focused_row_beside_the_list(self):
        lines = frame(menu(), 1, 200, 40)
        self.assertLessEqual(len(lines), 40)
        self.assertTrue(all(cell_len(line) <= 200 for line in lines))
        divider = lines[2].index("│")
        self.assertGreater(divider, 100)
        right = [line[divider + 1:].strip() for line in lines if len(line) > divider and line[divider] == "│"]
        self.assertEqual(right[:6], ["Anime", "Nyaa", "", "Anime from Nyaa.", "", "ENGINES"])
        self.assertNotIn("Anime from Nyaa.", "\n".join(line[:divider] for line in lines))  # moved, not repeated
        self.assertIn("Books from Libgen.", "\n".join(frame(menu(), 2, 200, 40)))

    def test_narrow_windows_and_rows_without_help_keep_one_column(self):
        self.assertFalse(any("│" in line for line in frame(menu(), 1, 149, 40)))
        plain = [SelectItem("One"), SelectItem("Two")]
        self.assertFalse(any("│" in line for line in frame(plain, 0, 200, 40)))

    def test_a_heading_beside_the_pane_keeps_its_style_to_itself(self):
        screen = Console(file=io.StringIO(), width=200, height=40)
        with patch.object(selector, "console", screen):
            group = selector._build_panel(menu(), 1, "Menu", False)
        for line in group.renderables:
            if "SHELVES" in line.plain and "│" in line.plain:
                start = line.plain.index("│") + 3  # the pane's text on the heading's row
                self.assertTrue(line.plain[start:].strip())
                styles = [str(span.style) for span in line.spans if span.start <= start < span.end]
                self.assertNotIn(theme.SECTION, styles)
                break
        else:
            self.fail("the heading row should carry the pane's first line")

    def test_a_tall_pane_is_cut_and_the_tip_spans_the_window(self):
        long = [SelectItem("Row", "row", description="x", inspect=lambda: [Text(f"line {i}") for i in range(80)])]
        lines = frame(long, 0, 200, 30)
        self.assertEqual(len(lines), 30)
        self.assertTrue(any(line.rstrip().endswith("…") for line in lines))
        tip = "[accent]Tip[/accent]  " + "word " * 50
        lines = frame(menu(), 1, 200, 40, tip=tip)
        self.assertTrue(lines[-1].strip().startswith("word") or lines[-2].strip().startswith("Tip"))
        self.assertNotIn("│", lines[-1])

    def test_the_athanor_frame_holds_the_pane(self):
        theme.apply("citrinitas", focus="fill", density="comfortable")
        lines = frame(menu(), 1, 200, 40)
        self.assertEqual(len(lines), 40)
        self.assertEqual(len({cell_len(line) for line in lines}), 1)  # every row as wide as the frame
        self.assertTrue(lines[1].startswith("╔═ torrent-finder"))
        self.assertIn("│  Anime", lines[2])


class DetailsTests(unittest.TestCase):
    def test_details_are_read_once_and_a_failing_source_shows_nothing(self):
        calls = []
        item = SelectItem("Row", inspect=lambda: calls.append(1) or [Text("a")])
        self.assertEqual([line.plain for line in item.details()], ["a"])
        item.details()
        self.assertEqual(calls, [1])
        broken = SelectItem("Row", inspect=lambda: 1 / 0)
        self.assertEqual(broken.details(), [])


class HomeDetailsTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)

    def plain(self, lines) -> list[str]:
        return [line.plain for line in lines]

    def test_a_provider_lists_engines_presets_recent_searches_and_counts(self):
        engines = [SimpleNamespace(name="Nyaa", mode="on", description="Anime categories. More."),
                   SimpleNamespace(name="SolidTorrents", mode="off", description=""),
                   SimpleNamespace(name="Knaben", mode="auto", description="")]
        provider = SimpleNamespace(slug="anime", engines=engines, active_presets=[],
                                   preferred_presets=[SimpleNamespace(name="1080p")])
        state.add_history_entry("frieren", "anime")
        state.add_history_entry("dune", "movies")
        with patch("torrent_finder.stats.get_all_stats",
                   return_value={"searches_by_provider": {"anime": 4}, "torrents_picked_by_provider": {"anime": 2}}):
            lines = self.plain(inspector.provider(provider))
        self.assertEqual(lines[0], "ENGINES")
        self.assertTrue(lines[1].startswith("  Nyaa") and "On" in lines[1] and lines[1].endswith("Anime categories"))
        self.assertIn("SolidTorrents  Off", lines[2])  # long names keep their gap
        self.assertIn("  Prefer      1080p", lines)
        recent = lines.index("RECENT HERE")
        self.assertTrue(lines[recent + 1].strip().startswith("frieren"))
        self.assertNotIn("dune", "\n".join(lines))
        self.assertEqual(lines[-1].strip(), "4 searches · 2 picked")

    def test_continue_lists_the_searches_before_it(self):
        for query in ("first", "second", "third"):
            state.add_history_entry(query, "movies")
        newest = state.load_history()[0]
        lines = self.plain(inspector.continue_search(newest))
        self.assertIn("RECENT SEARCHES", lines)
        listed = "\n".join(lines)
        self.assertIn("second", listed)
        self.assertNotIn("third", listed)  # the Continue row itself
        self.assertTrue(lines[-1].strip().startswith("H opens"))

    def test_credentials_folder_and_settings(self):
        credentials = self.plain(inspector.credentials())
        self.assertEqual(credentials[0], "LOGINS AND KEYS")
        self.assertTrue(all("  " in line.strip() for line in credentials[1:]))  # name, a gap, the status
        folder = self.plain(inspector.download_folder("Z:/no/such/folder/anywhere"))
        self.assertIn("Unpack", "\n".join(folder))
        settings = self.plain(inspector.settings())
        self.assertIn("  Design      Simple · Quiet Blue", settings)

    def test_main_menu_rows_carry_their_details(self):
        state.add_history_entry("dune", "movies")
        captured = []
        with patch.object(prompts, "arrow_select", side_effect=lambda items, **kw: captured.append(items)):
            prompts.provider_select_prompt()
        def key(value):
            if isinstance(value, str):
                return value
            return value[0] if isinstance(value, tuple) else getattr(value, "slug", None)

        rows = {key(item.value): item for item in captured[0] if item.enabled}
        for key in ("continue", "movies", "__credentials__", "__download_dir__", "__settings__"):
            self.assertIsNotNone(rows[key].inspect, key)
        self.assertEqual(rows["movies"].details()[0].plain, "ENGINES")


if __name__ == "__main__":
    unittest.main()
