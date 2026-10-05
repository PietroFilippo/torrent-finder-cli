"""The Athanor chrome: frame, message line, status line, and screens fitted inside them."""

import datetime as dt
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

from torrent_finder import security, state
from torrent_finder.providers.combined_provider import EngineProgress, ProviderProgress, SearchProgress
from torrent_finder.ui import chrome, prompts, search_progress, selector, theme
from torrent_finder.ui.selector import SelectItem


class AthanorCase(unittest.TestCase):
    def setUp(self):
        theme.apply("citrinitas", focus="bar", density="comfortable")
        chrome.clear_messages()
        self.addCleanup(chrome.clear_messages)  # the suite's Simple baseline comes back after each test


def lines_of(texts) -> list[str]:
    return [text.plain for text in texts]


class ComposeTests(AthanorCase):
    def test_rows_left_for_content(self):
        self.assertEqual(theme.view_height(24, 80), 20)   # frame edges, message and status lines
        self.assertEqual(theme.view_height(20, 80), 18)   # no room for the two lines: edges only
        self.assertEqual(theme.view_height(11, 80), 11)   # tiny: no frame at all
        self.assertEqual(theme.view_height(24, 30), 24)   # too narrow for a frame
        theme.apply(density="compact")
        self.assertEqual(theme.view_height(40, 120), 38)  # compact keeps the frame, drops the lines
        theme.apply("quiet")
        self.assertEqual(theme.view_height(24, 80), 24)   # Simple has no chrome

    def test_content_sits_inside_the_frame_with_the_name_in_its_top_edge(self):
        body = [Text("  Row one"), Text("  Row two")]
        out = lines_of(chrome.compose(body, "Filters › Movies & Series", "3 on", 60, 24, "A raven arrives."))
        self.assertEqual(len(out), 24)
        self.assertTrue(all(cell_len(line) == 60 for line in out))
        self.assertIn("A raven arrives.", out[0])
        self.assertTrue(out[1].startswith("╔═ torrent-finder » Filters » Movies & Series"))
        self.assertTrue(out[1].endswith(" 3 on ═╗"))
        self.assertEqual(out[2], "║ Row one" + " " * 50 + "║")  # the border takes the outer margin cell
        self.assertTrue(out[-2].startswith("╚") and out[-2].endswith("╝"))
        self.assertIn("Searches:", out[-1])

    def test_unframed_content_passes_through(self):
        theme.apply("quiet")
        body = [Text("  one")]
        self.assertIs(chrome.compose(body, "X", "", 80, 24), body)

    def test_frame_colours_and_text_colour_follow_the_colourway(self):
        out = chrome.compose([Text("  plain words")], "Menu", "", 60, 24)
        side = out[2]
        self.assertEqual(str(side.spans[0].style), theme.FRAME)
        self.assertIn(theme.TEXT, [str(span.style) for span in side.spans])  # plain text in parchment

    def test_long_titles_and_statuses_are_cut_to_the_edge(self):
        out = chrome.top_edge("Download › " + "x" * 120, "3–19 of 23 · 1.4 GB · 812 seeds", 50)
        self.assertEqual(cell_len(out.plain), 50)
        self.assertTrue(out.plain.endswith("╗"))


class MessageTests(AthanorCase):
    def test_announcements_come_one_per_screen_with_more_when_others_wait(self):
        chrome.announce("first")
        chrome.announce("second")
        chrome.announce("first")  # a repeat waiting in the queue is dropped
        self.assertEqual(chrome.take_message(), "first [reverse]--More--[/reverse]")
        self.assertEqual(chrome.take_message(), "second")
        self.assertEqual(chrome.take_message(), "")

    def test_the_status_line_counts_and_dates(self):
        isolate_store(self)
        chrome.turn()
        security._exposure["state"] = "exposed"
        self.addCleanup(security._exposure.update, state=None)
        line = chrome.status_line(80, now=dt.datetime(2026, 10, 4, 9, 41)).plain
        self.assertRegex(line, r"Searches:\d+ +Picked:\d+ +Bookmarks:\d+ +T:\d+")
        self.assertIn("Sun 4 Oct", line)
        self.assertIn("IP visible", line)
        self.assertEqual(cell_len(line), 80)
        self.assertNotIn("Sun", chrome.status_line(30).plain)  # narrow: the figures stay, the rest goes


class FramedScreenTests(AthanorCase):
    SIZES = ((40, 12), (50, 16), (80, 24), (120, 40))

    def test_menus_fit_with_the_alert_on_the_message_line(self):
        items = [SelectItem(f"Row {i}") for i in range(30)]
        for width, height in self.SIZES:
            with self.subTest(width=width, height=height):
                screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
                with patch.object(selector, "console", screen):
                    panel = selector._build_panel(items, 0, "Select Provider", False, "Enter select • Esc quit",
                                                  alert="Press Esc or Ctrl+C again to quit")
                screen.print(panel)
                out = screen.file.getvalue().rstrip("\n").split("\n")
                self.assertLessEqual(len(out), height)
                self.assertTrue(all(cell_len(line) <= width for line in out))
                text = "\n".join(out)
                self.assertIn("@ Row 0", text)
                self.assertIn("Esc quit", text)
                if theme.bars(width, height):
                    self.assertIn("again to quit", out[0])  # the message line, above the frame
                self.assertIn("again to quit", text)

    def test_the_text_field_cursor_lands_on_the_field(self):
        render = prompts.input_screen("Profile name", "Use a unique name.")
        for width, height in self.SIZES:
            with self.subTest(width=width, height=height):
                content, row, col = prompts._render_query_frame(render, prompts.PROMPT, [], list("Saki"), 4,
                                                                width, height)
                lines = Text.from_ansi(content).plain.split("\n")
                self.assertLessEqual(len(lines), height)
                self.assertIn("› Saki", lines[row - 1])
                self.assertEqual(lines[row - 1][col - 2], "i")
                if theme.framed(width, height):
                    self.assertIn("Profile name", "\n".join(lines[:2]))  # in the frame's top edge

    def test_search_progress_says_what_happened_last(self):
        providers = (ProviderProgress("Movies & Series", "done", 28, (EngineProgress("Apibay", "results", 20),)),
                     ProviderProgress("Manga · General", "failed", 0, (EngineProgress("Knaben", "timeout"),)),
                     ProviderProgress("Anime", "running", 0, (EngineProgress("Nyaa", "searching"),)))
        progress = SearchProgress(2, 3, 28, ("Anime",), providers)
        self.assertEqual(search_progress.progress_message(progress, "Contacting…"), "Manga · General falls silent.")
        self.assertEqual(search_progress.progress_message(None, "Contacting…"), "Contacting…")
        screen = Console(file=io.StringIO(), width=80, height=24, color_system=None)
        with patch.object(search_progress, "console", screen):
            frame = search_progress.progress_frame("Search › dune", "Searching dune", [], progress, 3.0, "…")
        screen.print(frame)
        out = screen.file.getvalue().rstrip("\n").split("\n")
        self.assertEqual(len(out), 24)
        self.assertIn("falls silent", out[0])

    def test_the_main_menu_shows_its_room_in_tall_windows(self):
        isolate_store(self)
        state.add_history_entry("dune", "movies")
        captured = {}
        with patch.object(prompts, "arrow_select", side_effect=lambda items, **kw: captured.update(kw)):
            prompts.provider_select_prompt()
        for height, shown in ((24, False), (40, True)):
            with patch.object(prompts, "console", Console(file=io.StringIO(), width=100, height=height)):
                room = captured["intro"]()
            self.assertEqual(bool(room), shown)
        self.assertEqual(room[0].plain, "~ The Index ~")
        self.assertIn("Obvious exits: continue (dune)", room[2].plain)

    def test_simple_design_frames_are_unchanged(self):
        theme.apply("quiet")
        screen = Console(file=io.StringIO(), width=80, height=24, color_system=None)
        with patch.object(selector, "console", screen):
            screen.print(selector._build_panel([SelectItem("Row")], 0, "Menu", False))
        out = screen.file.getvalue().split("\n")
        self.assertTrue(out[0].startswith("  torrent-finder › Menu"))
        self.assertNotIn("╔", screen.file.getvalue())


if __name__ == "__main__":
    unittest.main()
