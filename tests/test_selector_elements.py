"""Selector elements: styled hints, the intro line, filled focus and the key list."""

import io
import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from torrent_finder.ui import selector, theme
from torrent_finder.ui.selector import SelectItem


def frame_lines(items, width=80, height=24, cursor=0, **kwargs):
    screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
    with patch.object(selector, "console", screen):
        frame = selector._build_panel(items, cursor, kwargs.pop("title", "Menu"), False,
                                      kwargs.pop("footer", "↑/↓ navigate • Enter select • Esc back"), **kwargs)
        screen.print(frame)
    return frame, screen.file.getvalue().rstrip("\n").split("\n")


def row_of(frame, label):
    return next(line for line in frame.renderables if isinstance(line, Text) and label in line.plain)


def style_of(line, word):
    return [str(span.style) for span in line.spans if line.plain[span.start:span.end].strip() == word]


class StyledHintTests(unittest.TestCase):
    def test_a_styled_hint_keeps_its_colours_and_lines_up_by_its_text(self):
        state = Text.assemble(("timed out", theme.WARN), " · 30.0 s")
        items = [SelectItem("Apibay", hint=Text.assemble(("results", theme.GOOD))), SelectItem("Knaben", hint=state)]
        frame, lines = frame_lines(items, width=100)
        apibay, knaben = row_of(frame, "Apibay"), row_of(frame, "Knaben")
        self.assertEqual(apibay.plain.index("results"), knaben.plain.index("timed out"))
        self.assertIn(theme.GOOD, style_of(apibay, "results"))
        self.assertIn(theme.WARN, style_of(knaben, "timed out"))
        # The unstyled part of a styled hint is steel, like any other hint.
        self.assertTrue(any(str(span.style) == theme.MUTED for span in knaben.spans))

    def test_a_hint_too_long_to_sit_inline_shows_above_the_keys_in_colour(self):
        hint = Text.assemble(("Movies", theme.ACCENT), " & Series, Anime, Manga · General · profile Default")
        frame, lines = frame_lines([SelectItem("Search across providers", hint=hint)], width=60)
        self.assertIn("Movies & Series, Anime", "\n".join(lines))
        shown = next(line for line in frame.renderables if isinstance(line, Text) and "Movies & Series" in line.plain)
        self.assertIn(theme.ACCENT, style_of(shown, "Movies"))

    def test_a_styled_label_and_a_coloured_marker(self):
        label = Text.assemble(("dune", theme.ACCENT), " part two")
        frame, _ = frame_lines([SelectItem(label, marker="●", marker_style=theme.GOOD), SelectItem("Other")], cursor=1)
        row = row_of(frame, "dune part two")
        self.assertIn(theme.ACCENT, style_of(row, "dune"))
        self.assertIn(theme.GOOD, style_of(row, "●"))


class IntroTests(unittest.TestCase):
    def test_the_intro_sits_under_the_header_and_gives_way_in_tiny_windows(self):
        items = [SelectItem(f"Row {i}") for i in range(30)]
        intro = "Nyaa · 1.4 GB · [good]812[/good] seeds · 140 leeches"
        _, lines = frame_lines(items, 80, 24, intro=intro)
        self.assertIn("812 seeds", lines[2])  # header, rule, intro
        for width, height in ((40, 8), (40, 12), (50, 16)):
            with self.subTest(width=width, height=height):
                _, lines = frame_lines(items, width, height, intro=intro * 3)
                self.assertLessEqual(len(lines), height)
                self.assertTrue(any("Row 0" in line for line in lines))
                self.assertIn("Esc back", "\n".join(lines))


class FilledFocusTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(theme.apply, focus="bar")

    def test_filled_focus_tints_the_focused_row_to_the_right_margin(self):
        theme.apply(focus="fill")
        frame, _ = frame_lines([SelectItem("Open in qBittorrent", hint="recommended"), SelectItem("aria2c")])
        focused, other = row_of(frame, "Open in qBittorrent"), row_of(frame, "aria2c")
        width = Console(file=io.StringIO(), width=80, height=24).size.width  # 79 off a Windows terminal
        self.assertEqual(cell_len(focused.plain), width - len(theme.MARGIN))
        fill = [span for span in focused.spans if f"on {theme.FILL}" in str(span.style)]
        self.assertEqual((fill[0].start, fill[0].end), (len(theme.MARGIN), len(focused.plain)))
        self.assertFalse(any("on " in str(span.style) for span in other.spans))

    def test_the_cursor_bar_alone_marks_focus_by_default(self):
        frame, _ = frame_lines([SelectItem("Open"), SelectItem("Other")])
        self.assertFalse(any("on " in str(span.style) for span in row_of(frame, "Open").spans))


class KeyListTests(unittest.TestCase):
    def test_help_joins_the_key_bar_only_when_it_needs_no_extra_line(self):
        items = [SelectItem("Row")]
        _, roomy = frame_lines(items, 80, 24, help_key=True)
        self.assertIn("? keys", roomy[-1])
        footer = "↑/↓ navigate • Enter select • F filters • H history • S stats • T tips • Tab actions • Esc cancel"
        _, plain = frame_lines(items, 80, 24, footer=footer)
        _, helped = frame_lines(items, 80, 24, footer=footer, help_key=True)
        self.assertEqual(len(plain), len(helped))

    def test_the_key_list_names_the_screen_keys_then_the_standard_ones(self):
        pairs = selector.key_pairs("Enter open • Space select • ←/→ page • Esc back", selector._STANDARD_KEYS)
        self.assertEqual(pairs[:4], [("Enter", "open"), ("Space", "select"), ("←/→", "page"), ("Esc", "back")])
        self.assertIn(("PgUp/PgDn", "page"), pairs)
        self.assertEqual(sum(key == "Esc" for key, _ in pairs), 1)  # not listed twice

    def test_question_mark_opens_the_key_list_and_returns_to_the_screen(self):
        keys = iter(["?", "\x1b"])
        shown = []
        out = io.StringIO()
        with patch.object(selector.readchar, "readkey", side_effect=lambda: next(keys)), \
             patch.object(selector, "show_keys", side_effect=lambda title, footer: shown.append((title, footer))), \
             patch.object(selector.sys, "stdout", out):
            result = selector.arrow_select([SelectItem("Row")], title="Menu", footer="Enter open • Esc back")
        self.assertIsNone(result)
        self.assertEqual(shown, [("Menu", "Enter open • Esc back")])
        self.assertGreaterEqual(out.getvalue().count("\033[?1049h"), 2)  # the screen is taken back

    def test_a_screen_that_binds_question_mark_keeps_it(self):
        keys = iter(["?"])
        with patch.object(selector.readchar, "readkey", side_effect=lambda: next(keys)), \
             patch.object(selector, "show_keys") as show, patch.object(selector.sys, "stdout", io.StringIO()):
            result = selector.arrow_select([SelectItem("Row")], hotkeys={"?": "mine"})
        self.assertEqual(result, ("hotkey", "mine", 0))
        show.assert_not_called()


if __name__ == "__main__":
    unittest.main()
