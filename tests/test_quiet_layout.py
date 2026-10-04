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


class SecurityWarningTests(unittest.TestCase):
    INFO = {"query": "203.0.113.7", "isp": "Example ISP", "org": "Example Org",
            "as": "AS64500 Example", "country": "Brazil"}

    def frames(self, width, height, keys, force=False):
        from torrent_finder import security
        frames = []
        screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
        with patch.object(security, "console", screen), \
             patch.object(security, "_fetch_network_info", return_value=self.INFO), \
             patch.object(security, "_render", lambda banner, frame, **kw: frames.append(frame)), \
             patch.object(security, "load_setting", return_value=False), \
             patch.dict(security.os.environ, {"TORRENT_SKIP_WARNING": ""}), \
             patch.object(security, "save_setting") as save, \
             patch.object(security.readchar, "readkey", side_effect=keys), \
             patch.object(security.sys, "stdout", io.StringIO()):
            result = security.show_security_warning(force=force)
        return result, frames, save

    def test_warning_fits_small_windows_and_keeps_the_essentials(self):
        for width, height in ((50, 16), (80, 24)):
            with self.subTest(width=width, height=height):
                result, frames, _ = self.frames(width, height, ["\r"])
                lines = plain_lines(frames[-1], width, height)
                output = "\n".join(lines)
                self.assertTrue(result)
                self.assertLessEqual(len(lines), height)
                for text in ("203.0.113.7", "Example ISP", "no VPN detected", "public", "Esc abort",
                             "don't show again"):
                    self.assertIn(text, output.replace("\n  ", " "))

    def test_keys_keep_their_meaning(self):
        self.assertFalse(self.frames(80, 24, ["\x1b"])[0])
        self.assertFalse(self.frames(80, 24, [KeyboardInterrupt()])[0])
        result, _, save = self.frames(80, 24, ["d"])
        self.assertTrue(result)
        save.assert_called_once()


class ConfirmPromptTests(unittest.TestCase):
    def ask(self, key, width=50, height=16):
        out = io.StringIO()
        screen = Console(file=out, width=width, height=height, color_system=None)
        with patch.object(prompts, "console", screen), \
             patch.object(prompts.readchar, "readkey", return_value=key), \
             patch.object(prompts.sys, "stdout", io.StringIO()):
            answer = prompts.confirm_prompt("[error]Clear all search history?[/error]\n\nThis cannot be undone.",
                                            title="Clear history")
        return answer, out.getvalue()

    def test_y_confirms_and_other_keys_cancel(self):
        self.assertTrue(self.ask("y")[0])
        self.assertTrue(self.ask("Y")[0])
        self.assertFalse(self.ask("n")[0])
        self.assertFalse(self.ask("\x1b")[0])

    def test_dialog_fits_and_names_the_keys(self):
        _, output = self.ask("n")
        lines = output.rstrip("\n").split("\n")
        self.assertLessEqual(len(lines), 16)
        self.assertIn("Clear history", lines[0])
        self.assertIn("Y confirm", output)
        self.assertIn("Esc cancel", output)


class HintColumnTests(unittest.TestCase):
    def frame(self, items):
        screen = Console(file=io.StringIO(), width=100, height=30, color_system=None)
        with patch.object(selector, "console", screen):
            return plain_lines(selector._build_panel(items, 0, "Menu", False), 100, 30)

    def test_hints_line_up_within_a_run_of_hinted_rows_only(self):
        lines = self.frame([
            SelectItem("Search again", hint="R"), SelectItem("Change provider", hint="P"),
            SelectItem("No hint here"),
            SelectItem("Quick actions", hint="Tab"),
            SelectItem("Another plain row"),
        ])
        again = next(line for line in lines if "Search again" in line)
        change = next(line for line in lines if "Change provider" in line)
        self.assertEqual(again.index("R"), change.index("P"))
        quick = next(line for line in lines if "Quick actions" in line)
        self.assertIn("Quick actions  Tab", quick)


class DownloadMenuHeaderTests(unittest.TestCase):
    def test_download_menu_names_the_picked_torrent(self):
        captured = {}
        def capture(items, **kwargs):
            captured.update(kwargs)
            return None
        torrent = {"name": "Big Buck Bunny [1080p]", "size": 885_700_000, "seeders": 12}
        with patch.object(prompts, "arrow_select", side_effect=capture):
            prompts.download_method_prompt(magnet="magnet:?xt=urn:btih:" + "ab" * 20, torrent=torrent,
                                           show_episode_picker=True, selected_indexes=[1, 2])
        title = Text.from_markup(captured["title"]).plain
        self.assertIn("Big Buck Bunny [1080p]", title)
        self.assertIn("2 episode(s) selected [1-2]", title)
        self.assertIn("12 seeds", captured["status"])


class HeadingEscapeTests(unittest.TestCase):
    def test_queries_with_brackets_render_literally_in_the_results_header(self):
        from torrent_finder import main
        from torrent_finder.search_session import SearchResults
        session = SimpleNamespace(queries=["dune [/x]", "[bold]frieren"])
        results = SearchResults([{"name": "Dune", "source": "Nyaa"}], session=session)
        provider = SimpleNamespace(name="Anime", slug="anime", result_sort="relevance",
                                   filter_summary=lambda: "No presets")
        seen = {}
        def capture(rows, **kwargs):
            seen.update(kwargs)
            return None
        with patch.object(main, "interactive_select", side_effect=capture), \
             patch.object(main, "clear_screen"):
            self.assertEqual(main._browse_results(provider, results), "back")
        header = " ".join(line.plain for line in theme.header_lines(seen["heading"], "", 120))
        self.assertIn("dune [/x], [bold]frieren", header)


class CredentialFieldTailTests(CredentialFormTests):
    def test_long_values_keep_their_end_and_caret_visible_in_narrow_windows(self):
        keys = list("http://127.0.0.1:8080") + ["\x03"]
        _, buffers, frames, meta = self.run_form(keys, width=50, height=16)
        output = "\n".join(plain_lines(frames[-1], 50, 16))
        self.assertIn("0.1:8080█", output)
        self.assertTrue(all(cell_len(line) <= 50 for line in output.splitlines()))
        self.assertEqual(buffers[meta.fields[0].env_key], "http://127.0.0.1:8080")


class ReviewRoundOneTests(unittest.TestCase):
    def test_spinner_advances_with_elapsed_time(self):
        frames = {search_progress.spinner_frame(t / 10) for t in range(10)}
        self.assertGreater(len(frames), 3)

    def test_ctrl_c_during_an_acquisition_wait_cancels_the_worker(self):
        import threading
        from torrent_finder import acquisition
        seen = {}
        started = threading.Event()

        def work(cancel_event):
            seen["event"] = cancel_event
            started.set()
            cancel_event.wait(2)
            return "late"

        import contextlib
        real_join = threading.Thread.join

        def interrupted_join(thread, timeout=None):
            if timeout == 0.1:  # the wait loop's poll: Ctrl+C arrives here
                raise KeyboardInterrupt
            return real_join(thread, timeout)

        listener = threading.Event()
        with patch("torrent_finder.utils.start_esc_listener", return_value=listener), \
             patch.object(acquisition.console, "status", return_value=contextlib.nullcontext()), \
             patch.object(threading.Thread, "join", interrupted_join):
            with self.assertRaises(KeyboardInterrupt):
                acquisition._wait_with_esc("Fetching", work)
        self.assertTrue(started.wait(2))
        self.assertTrue(seen["event"].is_set())  # the worker was told to stop
        self.assertTrue(listener.is_set())

    def test_menus_with_pinned_actions_fit_after_paging(self):
        items = [SelectItem(f"History entry {i} with a long label", hint="Anime • 3d ago") for i in range(30)]
        items += [SelectItem("Clear history", is_action=True), SelectItem("Back", is_action=True)]
        footer = "↑/↓ navigate • Enter re-run • Esc back • P provider: All • T type: All • D date: All time"
        for width, height in ((40, 12), (50, 12), (60, 20)):
            with self.subTest(width=width, height=height):
                screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
                with patch.object(selector, "console", screen):
                    frame = selector._build_panel(items, 31, "Search History · provider: All · type: All",
                                                  False, footer)
                self.assertLessEqual(len(plain_lines(frame, width, height)), height)


class ResultsBudgetTests(unittest.TestCase):
    def test_long_details_never_push_the_keys_off_screen(self):
        from rich.console import Group
        from torrent_finder.ui import table
        works = ["The Lord of the Rings: The Fellowship of the Ring (2001)", "Dune", "Alien"]
        rows = [dict(name=f"Release {i} 1080p WEB-DL", source="Apibay", seeders=10 + i, leechers=3,
                     size=1_000_000_000, uploaded_at=1_700_000_000, from_work=works[i % 3],
                     apibay_cached_at=1.0) for i in range(20)]  # cached rows add a note line
        heading = "Movies & Series › lord of the rings, dune, alien"
        for width, height in ((80, 24), (60, 20), (100, 30)):
            for focus in range(0, 20, 3):
                with self.subTest(width=width, height=height, focus=focus):
                    screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
                    with patch.object(table, "console", screen):
                        count = table._visible_count(len(rows), height, width, "", True, False,
                                                     heading=heading, rows=rows, indexes=range(20))
                        scroll = max(0, focus - count + 1)
                        frame = Group(*theme.header_lines(heading, "1–13 of 20 · page 1/2", width), Text(""),
                                      Text("  Sort: Recommended • contains: all names"),
                                      table.build_table(rows, focus, scroll, count, len(rows), show_from=True,
                                                        original_indices=list(range(20))))
                        lines = plain_lines(frame, width, height)
                    self.assertLessEqual(len(lines), height)
                    self.assertIn("Esc back", "\n".join(lines))


class TextFieldFrameTests(unittest.TestCase):
    def frame(self, renderer, committed, text, pos, width, height):
        content, row, col = prompts._render_query_frame(renderer, prompts.PROMPT, committed, list(text), pos,
                                                        width, height)
        lines = Text.from_ansi(content).plain.split("\n")
        self.assertLessEqual(len(lines), height)
        self.assertTrue(all(cell_len(line) <= width for line in lines))
        return lines, row, col

    def assert_cursor_after(self, lines, row, col, before):
        """The cell left of the cursor shows the character typed before it."""
        line = lines[row - 1]
        self.assertGreaterEqual(len(line), col - 1)
        self.assertEqual(line[col - 2], before)

    def test_queued_titles_never_push_the_field_off_a_small_window(self):
        renderer = prompts.make_search_screen_renderer("Apibay, Knaben, YTS", "No presets", True, title="Movies")
        lines, row, col = self.frame(renderer, ["one", "two", "three", "four", "five"], "dune", 4, 40, 12)
        self.assertIn("› dune", lines[row - 1])
        self.assert_cursor_after(lines, row, col, "e")
        self.assertIn("torrent-finder", lines[0])
        self.assertIn("Esc", "\n".join(lines))

    def test_cursor_follows_wrapped_text(self):
        text = "a" * 25 + " " + "b" * 15
        for pos in (30, 26, 25, len(text)):
            with self.subTest(pos=pos):
                lines, row, col = self.frame(prompts.input_screen("Query"), [], text, pos, 40, 12)
                self.assert_cursor_after(lines, row, col, text[pos - 1])

    def test_long_help_gives_way_to_the_field_and_keys(self):
        from torrent_finder.ui.combined import _shared_filter_screen
        lines, row, col = self.frame(_shared_filter_screen("include_keywords"), [], "", 0, 50, 16)
        self.assertIn("›", lines[row - 1])
        self.assertIn("Esc cancel", lines[-1])
