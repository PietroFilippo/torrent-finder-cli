"""Simple shows announcements on a notice line above the key bar; Athanor keeps its message line."""

import io
import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirects saved settings before anything reads them
from rich.console import Console
from rich.text import Text

from torrent_finder.ui import chrome, prompts, selector, table, theme
from torrent_finder.ui.selector import SelectItem

KEYS = "↑/↓ navigate  •  Enter select  •  Esc back"
MESSAGE = "You find 7 results for dune."


def panel(width, height, **kwargs) -> list[str]:
    items = [SelectItem("Appearance", "appearance", description="Theme colours and spacing."),
             SelectItem("Back", None, is_action=True)]
    screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
    with patch.object(selector, "console", screen):
        screen.print(selector._build_panel(items, 0, "Settings", False, KEYS, **kwargs))
    return screen.file.getvalue().rstrip("\n").split("\n")


def row_of(lines: list[str], text: str) -> int:
    return next(i for i, line in enumerate(lines) if text in line)


class NoticeLineTests(unittest.TestCase):
    def setUp(self):
        chrome.clear_messages()
        self.addCleanup(theme.apply, "quiet", focus="bar", density="comfortable")

    def test_simple_shows_the_announcement_above_the_keys(self):
        theme.apply("quiet", focus="bar", density="comfortable")
        for width, height in [(80, 24), (137, 36), (60, 14)]:
            with self.subTest(width=width, height=height):
                lines = panel(width, height, message=MESSAGE)
                notice, keys = row_of(lines, MESSAGE), row_of(lines, "Enter select")
                self.assertLess(notice, keys)
                between = [line.strip() for line in lines[notice + 1:keys]]
                self.assertTrue(all(not line or set(line) == {theme.RULE} for line in between), between)
                self.assertLessEqual(len(lines), height)

    def test_simple_without_a_message_has_no_notice_row(self):
        theme.apply("quiet", focus="bar", density="comfortable")
        with_message, without = panel(80, 24, message=MESSAGE), panel(80, 24)
        self.assertNotIn(MESSAGE, "\n".join(without))
        filled = [len([line for line in lines if line.strip()]) for lines in (with_message, without)]
        self.assertEqual(filled[0] - filled[1], 1)  # the notice is the only extra row

    def test_athanor_keeps_its_message_line(self):
        theme.apply("citrinitas", focus="bar", density="comfortable")
        lines = panel(80, 24, message=MESSAGE)
        self.assertIn(MESSAGE, lines[0])  # the message line above the frame
        self.assertEqual(sum(MESSAGE in line for line in lines), 1)

    def test_every_design_has_somewhere_for_a_message(self):
        theme.apply("quiet")
        self.assertTrue(chrome.shows_message(80, 24))
        self.assertTrue(chrome.shows_message(40, 12))
        theme.apply("citrinitas")
        self.assertTrue(chrome.shows_message(80, 24))
        self.assertFalse(chrome.shows_message(80, 20))  # no bars: the message waits for a screen with them

    def test_the_notice_fits_the_width(self):
        theme.apply("quiet")
        line = chrome.notice_line("[warn]" + "x" * 100 + "[/warn]", 40)
        self.assertLessEqual(len(line.plain), 40)
        self.assertTrue(line.plain.endswith("…"))


class ResultsTableTests(unittest.TestCase):
    def setUp(self):
        chrome.clear_messages()
        self.addCleanup(theme.apply, "quiet", focus="bar", density="comfortable")

    def rows(self):
        return [dict(name=f"Dune part {i}", source="Apibay", seeders=20, leechers=2, size=1_000_000)
                for i in range(30)]

    def test_simple_results_show_the_notice_above_the_keys(self):
        theme.apply("quiet", focus="bar", density="comfortable")
        rows = self.rows()
        screen = Console(file=io.StringIO(), width=80, height=24, color_system=None)
        with patch.object(table, "console", screen), patch.object(prompts, "console", screen):
            count = table._visible_count(len(rows), 24, 80, "", False, announcement=MESSAGE)
            plain = table._visible_count(len(rows), 24, 80, "", False)
            screen.print(table.build_table(rows, 0, 0, count, len(rows), announcement=MESSAGE))
        lines = screen.file.getvalue().rstrip("\n").split("\n")
        self.assertEqual(plain - count, 2)  # the notice and the row above it come out of the results
        self.assertLess(row_of(lines, MESSAGE), row_of(lines, "Esc back"))
        self.assertLessEqual(len(lines) + 1, 24)  # with the header line the screen still fits

    def test_the_table_takes_the_message_in_simple(self):
        theme.apply("quiet", focus="bar", density="comfortable")
        chrome.announce(MESSAGE)
        self.assertTrue(chrome.shows_message(80, 24))
        theme.apply("citrinitas", density="compact")
        self.assertFalse(chrome.shows_message(80, 24))  # Athanor without bars: it waits
        self.assertEqual(chrome.take_message(), MESSAGE)


class SearchFieldTests(unittest.TestCase):
    def setUp(self):
        chrome.clear_messages()
        self.addCleanup(theme.apply, "quiet", focus="bar", density="comfortable")

    def test_simple_search_field_shows_the_notice_above_the_keys(self):
        theme.apply("quiet", focus="bar", density="comfortable")
        render = prompts.input_screen("Movies & Series", "Type a title.")
        for width, height in [(80, 24), (40, 12)]:
            with self.subTest(width=width, height=height):
                content, row, col = prompts._render_query_frame(render, prompts.PROMPT, [], list("dune"), 4,
                                                                width, height, message=MESSAGE)
                lines = Text.from_ansi(content).plain.split("\n")
                self.assertLessEqual(len(lines), height)
                self.assertLess(row_of(lines, "dune"), row_of(lines, MESSAGE))
                self.assertLess(row_of(lines, MESSAGE), row_of(lines, "Esc cancel"))
                self.assertIn("› dune", lines[row - 1])

    def test_athanor_search_field_keeps_the_message_line(self):
        theme.apply("citrinitas", focus="bar", density="comfortable")
        render = prompts.input_screen("Movies & Series", "Type a title.")
        content, row, col = prompts._render_query_frame(render, prompts.PROMPT, [], list("dune"), 4, 80, 24,
                                                        message=MESSAGE)
        lines = Text.from_ansi(content).plain.split("\n")
        self.assertIn(MESSAGE, lines[0])
        self.assertEqual(sum(MESSAGE in line for line in lines), 1)


if __name__ == "__main__":
    unittest.main()
