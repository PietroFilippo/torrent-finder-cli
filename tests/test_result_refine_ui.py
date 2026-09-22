import io
import unittest
from unittest.mock import patch

import readchar
from rich.console import Console, Group
from rich.text import Text
from torrent_finder.ui import table, selector, prompts
from torrent_finder.ui.selector import SelectItem


class ResultRefineUITests(unittest.TestCase):
    def _select(self, rows, refinement, keys):
        screen = Console(file=io.StringIO(), width=72, height=20, color_system=None)
        with patch.object(table, "console", screen), \
             patch.object(table, "refine_results", return_value=refinement), \
             patch.object(table.readchar, "readkey", side_effect=keys):
            return table.interactive_select(rows)

    def test_sorted_enter_returns_original_result_index(self):
        rows = [{"name":"Old", "uploaded_at":10}, {"name":"New", "uploaded_at":30}]
        self.assertEqual(self._select(rows, ("", "contains", "newest"), ["f", readchar.key.ENTER]), ("one", 1))

    def test_select_all_only_selects_visible_filtered_results(self):
        rows = [{"name":"Other"}, {"name":"Saki 720p"}, {"name":"Saki 1080p"}]
        self.assertEqual(self._select(rows, ("Saki", "title", "name"), ["f", "a", readchar.key.ENTER]), ("many", [1, 2]))

    def test_empty_filter_does_not_open_an_invalid_row(self):
        self.assertIsNone(self._select([{"name":"Other"}], ("Saki", "title", "name"), ["f", readchar.key.ENTER, readchar.key.ESC]))

    def test_numeric_jump_uses_the_displayed_id_after_sorting(self):
        rows = [{"name":"Old", "uploaded_at":10}, {"name":"New", "uploaded_at":30}]
        self.assertEqual(self._select(rows, ("", "contains", "newest"), ["f", "0", readchar.key.ENTER]), ("one", 0))

    def test_action_only_menus_scroll_and_keep_the_focused_row_visible(self):
        for width, height in [(40, 16), (60, 20), (80, 24)]:
            with self.subTest(width=width, height=height):
                screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
                items = [SelectItem(f"Action {i}", i, is_action=True) for i in range(40)]
                with patch.object(selector, "console", screen):
                    screen.print(selector._build_panel(items, 25, "Options", False))
                rendered = screen.file.getvalue()
                self.assertIn("Action 25", rendered)
                self.assertIn("/ 40", rendered)
                self.assertLessEqual(len(rendered.splitlines()), height - 1)

    def test_compact_selector_uses_border_position_instead_of_extra_rows(self):
        screen = Console(file=io.StringIO(), width=60, height=20, color_system=None)
        items = [SelectItem(f"Option {i}", i) for i in range(40)]
        with patch.object(selector, "console", screen):
            panel = selector._build_panel(items, 20, "Options", False)
            screen.print(panel)
        text = screen.file.getvalue()
        self.assertNotIn("more below", text)
        self.assertNotIn("more above", text)
        self.assertIn("/ 40", text)
        self.assertLessEqual(len(text.splitlines()), 19)

    def test_complete_multiselect_frame_reserves_banner_and_action_separator(self):
        for width, height in [(40, 16), (60, 20), (80, 24), (100, 30)]:
            with self.subTest(width=width, height=height):
                screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
                items = [SelectItem(f"Option {i}", i) for i in range(40)]
                items.extend([SelectItem("Confirm", "done", is_action=True), SelectItem("Back", "back", is_action=True)])
                with patch.object(selector, "console", screen), patch.object(prompts, "console", screen):
                    panel = selector._build_panel(items, 20, "Options", True)
                    banner = Text("Torrent Search CLI") if height < 28 else Group(prompts._make_banner_panel(), Text(""))
                    screen.print(Group(banner, panel))
                self.assertLessEqual(len(screen.file.getvalue().splitlines()), height)
