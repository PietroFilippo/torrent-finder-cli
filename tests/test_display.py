"""Flicker-free frames and the shared alternate screen."""

import io
import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirects saved settings before anything reads them
from rich.console import Console

from torrent_finder.ui import display, prompts, selector
from torrent_finder.ui.selector import SelectItem


class PaintTests(unittest.TestCase):
    def test_frames_overwrite_in_place_without_clearing(self):
        out = display.paint("short\n" + "x" * 10 + "\n\033[1mbold\033[0m", 10, 5)
        self.assertNotIn("\033[2J", out)
        self.assertTrue(out.startswith(display.BEGIN_UPDATE + "\033[H"))
        self.assertTrue(out.endswith(display.END_UPDATE))
        rows = out[len(display.BEGIN_UPDATE + "\033[H"):].split("\n")
        self.assertEqual(rows[0], "short\033[K")         # the rest of the old line goes
        self.assertEqual(rows[1], "x" * 10)              # a full line keeps its last cell
        self.assertTrue(rows[2].startswith("\033[1mbold\033[0m\033[K"))
        self.assertIn("\033[4;1H\033[J", rows[2])        # rows under the frame are erased

    def test_a_frame_that_fills_the_window_erases_nothing_below(self):
        out = display.paint("a\nb", 1, 2, after="\033[1;1H")
        self.assertEqual(out, display.BEGIN_UPDATE + "\033[Ha\nb\033[1;1H" + display.END_UPDATE)

    def test_wide_characters_count_by_cells(self):
        self.assertNotIn("\033[K", display.paint("╔═é全", 5, 1))


class ScreenTests(unittest.TestCase):
    def setUp(self):
        self.out = io.StringIO()
        patcher = patch.object(display.sys, "stdout", self.out)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_the_outermost_view_switches_screens(self):
        display.enter_screen()
        display.enter_screen(cursor=True)   # a text field over a menu
        self.assertEqual(self.out.getvalue().count("\033[?1049h"), 1)
        display.leave_screen(clear=True)
        self.assertNotIn("\033[?1049l", self.out.getvalue())
        self.assertTrue(self.out.getvalue().endswith("\033[?25l"))  # the menu underneath hides the cursor
        display.leave_screen(clear=True)
        self.assertTrue(self.out.getvalue().endswith("\033[?25h\033[?1049l\033[2J\033[H"))
        self.assertEqual(display.depth(), 0)

    def test_a_confirmation_over_a_menu_keeps_the_menu_on_the_alternate_screen(self):
        keys = iter(["\r", "y", "\x1b"])
        answers = []
        screen = Console(file=io.StringIO(), width=60, height=20, color_system=None)

        def ask(index, items):
            answers.append(prompts.confirm_prompt("Sure?"))
            self.assertEqual(display.depth(), 1)  # the confirmation closed; the menu's screen remains
            return True  # stay on the menu

        with patch.object(selector, "console", screen), patch.object(prompts, "console", screen), \
             patch.object(selector.readchar, "readkey", side_effect=lambda: next(keys)), \
             patch.object(prompts.readchar, "readkey", side_effect=lambda: next(keys)):
            selector.arrow_select([SelectItem("Act", "act", is_action=True)], title="Menu", on_action=ask)
        written = self.out.getvalue()
        self.assertEqual(answers, [True])
        self.assertEqual((written.count("\033[?1049h"), written.count("\033[?1049l")), (1, 1))
        self.assertTrue(written.endswith("\033[?1049l\033[2J\033[H"))  # left once, when the menu closed
        self.assertNotIn("\033[2J\033[H" + display.BEGIN_UPDATE, written)  # no frame starts on a blank screen


if __name__ == "__main__":
    unittest.main()
