"""The Quiet layout's shared pieces: footer parsing, header, key bar, progress screen."""

import io
import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from torrent_finder.ui import prompts, search_progress, selector, theme
from torrent_finder.ui.selector import SelectItem


def plain_lines(renderable, width, height=40):
    screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
    screen.print(renderable)
    return screen.file.getvalue().rstrip("\n").split("\n")


class FooterParsingTests(unittest.TestCase):
    def keys(self, footer):
        return [segment.plain for segment in theme.parse_footer(footer).keys]

    def test_key_segments_and_prose_are_separated(self):
        parsed = theme.parse_footer("Local JSON files • Enter choose • Esc back")
        self.assertEqual([k.plain for k in parsed.keys], ["Enter choose", "Esc back"])
        self.assertEqual([line.plain for line in parsed.context], ["Local JSON files"])

    def test_composite_and_modifier_keys(self):
        self.assertEqual(
            self.keys("↑/↓ nav • Space/Enter cycle • v/V range • Shift+V range • Ctrl+N add title"),
            ["↑/↓ nav", "Space/Enter cycle", "v/V range", "Shift+V range", "Ctrl+N add title"],
        )
        self.assertEqual(self.keys("U / F / H jump • Enter / Esc back"), ["U/F/H jump", "Enter/Esc back"])

    def test_markup_inside_keys_is_dropped_and_prose_keeps_its_style(self):
        parsed = theme.parse_footer(
            "[bold yellow]F[/bold yellow] filters\n[not dim bold yellow]Press Esc again to quit[/not dim bold yellow]")
        self.assertEqual([k.plain for k in parsed.keys], ["F filters"])
        notice = parsed.context[0]
        self.assertEqual(notice.plain, "Press Esc again to quit")
        self.assertTrue(any("yellow" in str(span.style) for span in notice.spans))

    def test_prose_that_starts_like_a_word_is_not_a_key(self):
        parsed = theme.parse_footer("Optional WebUI integration • Esc back")
        self.assertEqual([line.plain for line in parsed.context], ["Optional WebUI integration"])

    def test_plain_text_keys_keep_brackets(self):
        keys = theme.parse_footer(Text("i close • [/] scroll details")).keys
        self.assertEqual([k.plain for k in keys], ["i close", "[/] scroll details"])

    def test_a_footer_without_keys_still_gets_default_keys(self):
        screen = Console(width=60, height=20, color_system=None)
        with patch.object(selector, "console", screen):
            frame = selector._build_panel([SelectItem("One"), SelectItem("Two")], 0, "Title", False,
                                          "Catalog identifies works; release availability varies.")
        output = "\n".join(plain_lines(frame, 60))
        self.assertIn("Catalog identifies works", output)
        self.assertIn("Esc cancel", output)


class HeaderAndKeyBarTests(unittest.TestCase):
    def test_long_titles_continue_on_a_second_line(self):
        title = "Download Method — 4 episode(s) selected [1-3,7]"
        lines = theme.header_lines(title, "7–14 of 23", 50)
        self.assertEqual(len(lines), 2)
        joined = " ".join(line.plain for line in lines)
        self.assertIn("selected [1-3,7]", joined)
        self.assertIn("7–14 of 23", joined)
        self.assertTrue(all(cell_len(line.plain) <= 48 for line in lines))

    def test_short_titles_stay_on_one_line(self):
        self.assertEqual(len(theme.header_lines("Options", "1–9 of 40", 80)), 1)

    def test_key_bar_never_splits_a_segment(self):
        segments = theme.parse_footer("↑/↓ navigate • Enter select • F filters • H history • Esc cancel").keys
        for width in (30, 40, 60, 120):
            lines = [line.plain for line in theme.wrap_keys(segments, width)]
            joined = "   ".join(line.strip() for line in lines)
            for segment in segments:
                self.assertIn(segment.plain, joined)
            self.assertTrue(all(cell_len(line) <= width for line in lines), (width, lines))


class SearchProgressTests(unittest.TestCase):
    def test_progress_frame_fits_and_names_what_is_searched(self):
        progress = SimpleNamespace(completed=2, total=3, results=41, waiting=["Knaben", "Nyaa", "YTS"])
        for width, height in ((40, 12), (50, 16), (80, 24), (120, 40)):
            with self.subTest(width=width, height=height):
                screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
                with patch.object(search_progress, "console", screen):
                    frame = search_progress.progress_frame(
                        "Movies & Series › dune", "Searching Movies & Series for: dune",
                        ["30 s search limit; Enter shows the results received so far."],
                        progress, 3.4, "Searching…", 0.0)
                lines = plain_lines(frame, width, height)
                output = "\n".join(lines)
                self.assertLessEqual(len(lines), height)
                self.assertTrue(all(cell_len(line) <= width for line in lines))
                self.assertIn("Searching Movies & Series for: dune", output)
                self.assertIn("2/3 providers finished", output)
                self.assertIn("Waiting: Knaben, Nyaa +1 more", output)
                self.assertIn("Esc cancel", output)

    def test_screen_restores_the_terminal(self):
        out = io.StringIO()
        with patch.object(search_progress.sys, "stdout", out):
            with search_progress.ProgressScreen() as screen:
                screen.draw(Text("frame"))
        self.assertTrue(out.getvalue().startswith("\033[?1049h"))
        self.assertTrue(out.getvalue().endswith("\033[?25h\033[?1049l"))


class InputScreenTests(unittest.TestCase):
    def test_input_screen_puts_keys_below_the_field_and_the_cursor_on_it(self):
        render = prompts.input_screen("Profile name", "Use a unique name.", keys="Enter confirm • Esc cancel")
        for width, height in ((40, 10), (80, 24)):
            with self.subTest(width=width, height=height):
                content, row, col = prompts._render_query_frame(
                    render, prompts.PROMPT, [], list("Anime"), 5, width, height)
                lines = Text.from_ansi(content).plain.split("\n")
                self.assertLessEqual(len(lines), height)
                self.assertIn("Profile name", lines[0])
                self.assertIn("› Anime", lines[row - 1])
                self.assertIn("Esc cancel", lines[-1])
                self.assertEqual(col, cell_len("  › Anime") + 1)


if __name__ == "__main__":
    unittest.main()


class CredentialFormTests(unittest.TestCase):
    def run_form(self, keys, width=50, height=16):
        from torrent_finder.credential_registry import CREDENTIAL_REGISTRY
        from torrent_finder.ui import credentials as credentials_ui
        meta = next(m for m in CREDENTIAL_REGISTRY if m.howto)
        frames, buffers = [], {}
        screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
        with patch.object(credentials_ui, "console", screen), \
             patch.object(credentials_ui, "_render", lambda banner, frame, **kw: frames.append(frame)), \
             patch.object(credentials_ui.readchar, "readkey", side_effect=keys), \
             patch.object(credentials_ui.sys, "stdout", io.StringIO()):
            result = credentials_ui._credentials_form(meta, buffers)
        return result, buffers, frames, meta

    def test_ctrl_c_cancels_and_control_keys_are_not_typed(self):
        result, buffers, _, meta = self.run_form(["a", "\x0e", "\x03"])
        self.assertIsNone(result)
        self.assertEqual(buffers, {meta.fields[0].env_key: "a"})

    def test_sign_in_frame_fits_a_small_window(self):
        _, _, frames, _ = self.run_form(["\x03"])
        lines = plain_lines(frames[-1], 50, 16)
        self.assertLessEqual(len(lines), 16)
        self.assertIn("Esc cancel", "\n".join(lines))
