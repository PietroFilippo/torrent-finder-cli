"""Windows under 30x8 show one centred "Enlarge the window" line instead of a frame that overflows."""

import io
import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirects saved settings before anything reads them
import readchar
from rich.cells import cell_len
from rich.console import Console, ConsoleDimensions
from rich.text import Text

from torrent_finder.ui import chrome, display, prompts, selector, table, theme
from torrent_finder.ui.selector import SelectItem

KEYS = "↑/↓ navigate  •  Enter select  •  Esc back"
TINY = [(20, 6), (10, 3), (29, 8), (30, 7)]
SMALLEST_OK = (30, 8)


def plain_lines(text: str) -> list[str]:
    return [Text.from_ansi(line).plain for line in text.rstrip("\n").split("\n")]


class EnlargeNoticeTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(theme.apply, "quiet", focus="bar", density="comfortable")

    def test_the_notice_fits_the_window_exactly(self):
        for design in ("quiet", "citrinitas"):
            theme.apply(design, focus="bar", density="comfortable")
            for width, height in TINY:
                with self.subTest(design=design, width=width, height=height):
                    lines = chrome.enlarge_notice(width, height)
                    self.assertEqual(len(lines), height)
                    self.assertTrue(all(cell_len(line.plain) <= width for line in lines))
                    text = " ".join(line.plain.strip() for line in lines if line.plain.strip())
                    self.assertTrue(text.startswith("Enlarge the window"), text)
                    if height >= 4:
                        self.assertIn("30 columns by 8 rows", text)
                    else:
                        self.assertNotIn("columns", text)

    def test_athanor_says_it_in_its_voice(self):
        theme.apply("citrinitas")
        text = " ".join(line.plain.strip() for line in chrome.enlarge_notice(20, 6))
        self.assertIn("scriptorium", text)
        theme.apply("quiet")
        text = " ".join(line.plain.strip() for line in chrome.enlarge_notice(20, 6))
        self.assertNotIn("scriptorium", text)
        self.assertIn("at least", text)

    def test_the_line_is_centred(self):
        theme.apply("quiet")
        lines = chrome.enlarge_notice(40, 8)
        headline = next(line for line in lines if "Enlarge" in line.plain)
        left = len(headline.plain) - len(headline.plain.lstrip())
        self.assertEqual(left, (40 - len("Enlarge the window")) // 2)
        self.assertTrue(all(not line.plain for line in lines[:2]))  # vertically centred too


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(theme.apply, "quiet", focus="bar", density="comfortable")

    def frame(self, width, height) -> list[str]:
        items = [SelectItem("Movies & Series", "movies", hint="Apibay, Nyaa"), SelectItem("Back", None, is_action=True)]
        screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
        with patch.object(selector, "console", screen):
            screen.print(selector._build_panel(items, 0, "Select Provider", False, KEYS))
        return screen.file.getvalue().rstrip("\n").split("\n")

    def test_a_tiny_menu_shows_the_notice_and_nothing_else(self):
        for design in ("quiet", "citrinitas"):
            theme.apply(design, focus="bar", density="comfortable")
            for width, height in TINY:
                with self.subTest(design=design, width=width, height=height):
                    lines = self.frame(width, height)
                    self.assertLessEqual(len(lines), height)
                    self.assertIn("Enlarge", "\n".join(lines))
                    self.assertNotIn("Movies", "\n".join(lines))
                    self.assertNotIn("Enter", "\n".join(lines))

    def test_the_smallest_allowed_window_draws_the_menu(self):
        theme.apply("quiet", focus="bar", density="comfortable")
        lines = self.frame(*SMALLEST_OK)
        self.assertIn("Movies", "\n".join(lines))
        self.assertNotIn("Enlarge", "\n".join(lines))

    def test_the_menu_redraws_when_the_window_grows(self):
        theme.apply("quiet", focus="bar", density="comfortable")
        size = [ConsoleDimensions(20, 6)]
        painted = []

        def paint(content, width, height, after=""):
            painted.append(Text.from_ansi(content).plain)
            return ""

        keys = iter([readchar.key.DOWN, readchar.key.ESC])

        def key():
            size[0] = ConsoleDimensions(80, 24)  # the window grows before the next key
            return next(keys)

        with patch.object(type(selector.console), "size", property(lambda _self: size[0])), \
             patch.object(display, "paint", side_effect=paint), \
             patch.object(selector.sys, "stdout", io.StringIO()), \
             patch.object(selector.readchar, "readkey", side_effect=key):
            selector.arrow_select([SelectItem("Movies & Series", "movies"), SelectItem("Back", None, is_action=True)],
                                  title="Select Provider")
        self.assertIn("Enlarge", painted[0])
        self.assertIn("Movies & Series", painted[-1])
        self.assertNotIn("Enlarge", painted[-1])


class ResultsTableTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(theme.apply, "quiet", focus="bar", density="comfortable")

    def test_a_tiny_results_table_shows_the_notice(self):
        for design in ("quiet", "citrinitas"):
            for width, height in [(20, 6), (10, 3)]:
                with self.subTest(design=design, width=width, height=height):
                    theme.apply(design, focus="bar", density="comfortable")
                    rows = [dict(name=f"Dune part {i}", source="Apibay", seeders=20) for i in range(7)]
                    out = io.StringIO()
                    screen = Console(file=out, width=width, height=height, force_terminal=True, color_system="truecolor")
                    with patch.object(table, "console", screen), patch.object(prompts, "console", screen), \
                         patch.object(table.readchar, "readkey", side_effect=[readchar.key.ESC]):
                        table.interactive_select(rows)
                    lines = [line for line in plain_lines(out.getvalue()) if line.strip()]
                    text = "\n".join(lines)
                    self.assertIn("Enlarge", text)
                    self.assertNotIn("Sort:", text)
                    self.assertNotIn("Dune", text)


class TextFieldTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(theme.apply, "quiet", focus="bar", density="comfortable")

    def test_a_tiny_search_field_shows_the_notice(self):
        theme.apply("citrinitas", focus="bar", density="comfortable")
        render = prompts.input_screen("Movies & Series", "Type a title.")
        for width, height in TINY:
            with self.subTest(width=width, height=height):
                content, row, col = prompts._render_query_frame(render, prompts.PROMPT, [], list("dune"), 4,
                                                                width, height)
                lines = plain_lines(content)
                self.assertLessEqual(len(lines), height)  # trailing blank rows are stripped
                self.assertIn("Enlarge", "\n".join(lines))
                self.assertNotIn("dune", "\n".join(lines))
                self.assertTrue(1 <= row <= height and 1 <= col <= width)

    def test_a_tiny_confirmation_shows_the_notice(self):
        theme.apply("quiet", focus="bar", density="comfortable")
        size = [ConsoleDimensions(20, 6)]
        painted = []
        with patch.object(type(prompts.console), "size", property(lambda _self: size[0])), \
             patch.object(display, "paint", side_effect=lambda content, *a, **k: painted.append(content) or ""), \
             patch.object(selector.sys, "stdout", io.StringIO()), patch.object(prompts.sys, "stdout", io.StringIO()), \
             patch.object(prompts.readchar, "readkey", return_value="n"):
            self.assertFalse(prompts.confirm_prompt("Quit torrent-finder?", title="Quit"))
        self.assertIn("Enlarge", Text.from_ansi(painted[0]).plain)
        self.assertNotIn("Quit", Text.from_ansi(painted[0]).plain)


if __name__ == "__main__":
    unittest.main()
