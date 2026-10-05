"""Regressions found in the release review: text fields, nested views, small windows, the profile."""

import io
import json
import time
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirects saved settings before anything reads them
from isolation import isolate_store
from readchar import key as K
from rich.cells import cell_len
from rich.console import Console, ConsoleDimensions
from rich.text import Text

from torrent_finder import main, terminal_profile
from torrent_finder.ui import appearance, display, prompts, selector, theme
from torrent_finder.ui.selector import SelectItem


def plain(content: str) -> list[str]:
    return Text.from_ansi(content).plain.split("\n")


class TextFieldTests(unittest.TestCase):
    def setUp(self):
        theme.apply("citrinitas", focus="bar", density="comfortable")

    def test_a_queued_search_keeps_the_screen_name_and_is_never_markup(self):
        render = prompts.input_screen("Profile name", "Use a unique name.")
        content, _row, _col = prompts._render_query_frame(render, prompts.PROMPT, ["Dune", "[/oops]"], [], 0, 80, 24)
        lines = plain(content)
        self.assertIn("Profile name", lines[1])  # the frame's top edge
        self.assertNotIn("Dune", lines[1])
        self.assertIn("› [/oops]", "\n".join(lines))

    def test_long_text_folds_inside_the_frame_and_the_cursor_follows_it(self):
        render = prompts.input_screen("Profile name", "Use a unique name.")
        typed = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for width, height in ((40, 12), (50, 16), (80, 24)):
            with self.subTest(width=width, height=height):
                content, row, col = prompts._render_query_frame(render, prompts.PROMPT, [], list(typed),
                                                                len(typed), width, height)
                lines = plain(content)
                self.assertTrue(all(cell_len(line) <= width for line in lines))
                inside = "".join(line[1:-1].strip() for line in lines if line.startswith("║"))
                self.assertIn(typed, inside.replace("›", "").replace(" ", ""))  # no character hidden
                self.assertEqual(lines[row - 1][col - 2], "Z")  # the cursor sits just after the last one

    def test_a_failing_first_frame_leaves_its_screen(self):
        render = prompts.input_screen("Profile name")
        with patch.object(prompts, "_render_query_frame", side_effect=KeyboardInterrupt), \
             patch.object(prompts.sys, "stdout", io.StringIO()), \
             self.assertRaises(KeyboardInterrupt):
            prompts.get_query_with_shortcut(prompts.PROMPT, screen_renderer=render)
        self.assertEqual(display.depth(), 0)


class NestedViewTests(unittest.TestCase):
    def test_a_resize_during_a_callback_does_not_redraw_the_menu_over_it(self):
        size = [ConsoleDimensions(80, 24)]
        drawn = []

        def act(index, items):
            before = len(drawn)
            size[0] = ConsoleDimensions(100, 30)  # the window changes while a confirmation is open
            time.sleep(0.4)
            drawn.append(("during", len(drawn) - before))
            return True

        keys = iter([K.ENTER, K.ESC])
        with patch.object(type(selector.console), "size", property(lambda _self: size[0])), \
             patch.object(selector, "_render", side_effect=lambda *a, **k: drawn.append("frame") or True), \
             patch.object(selector.sys, "stdout", io.StringIO()), \
             patch.object(selector.readchar, "readkey", side_effect=lambda: next(keys)):
            selector.arrow_select([SelectItem("Act", "act", is_action=True)], title="Menu", on_action=act)
        during = next(entry for entry in drawn if isinstance(entry, tuple))
        self.assertEqual(during, ("during", 0))


class SmallWindowTests(unittest.TestCase):
    def frame(self, width, height, build) -> list[str]:
        screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
        with patch.object(selector, "console", screen), patch.object(prompts, "console", screen):
            screen.print(build())
        return screen.file.getvalue().rstrip("\n").split("\n")

    def test_the_confirmation_keeps_its_keys(self):
        theme.apply("citrinitas", focus="bar", density="comfortable")
        message = ("Add a [bold]torrent-finder[/bold] profile to Windows Terminal?\n\nIt opens the app with the "
                   "Citrinitas colours, Satan in profile behind the text and the PxPlus IBM VGA 8x16 font, "
                   "installed for your account. It appears when Windows Terminal restarts.")
        out = io.StringIO()
        screen = Console(file=io.StringIO(), width=40, height=12, color_system=None)
        with patch.object(prompts, "console", screen), patch.object(prompts.sys, "stdout", out), \
             patch.object(prompts.readchar, "readkey", return_value="n"):
            prompts.confirm_prompt(message, title="Windows Terminal profile")
        frame = out.getvalue().split(display.BEGIN_UPDATE)[-1].split(display.END_UPDATE)[0]
        text = Text.from_ansi(frame).plain
        self.assertIn("Y confirm", text)
        self.assertIn("Esc cancel", text)
        self.assertIn("…", text)  # the message's end gave way

    def test_athanor_without_a_message_line_shows_announcements_under_the_keys(self):
        theme.apply("citrinitas", focus="bar", density="compact")
        lines = self.frame(80, 24, lambda: selector._build_panel(
            [SelectItem("Row")], 0, "Menu", False, "Enter select • Esc back", message="A raven arrives."))
        keys = max(i for i, line in enumerate(lines) if "Esc back" in line)
        self.assertIn("A raven arrives.", lines[keys + 1])

    def test_a_tiny_window_never_scrolls_the_menu(self):
        items = [SelectItem(f"Row {i}", description="Some help for this row.") for i in range(5)]
        lines = self.frame(20, 8, lambda: selector._build_panel(
            items, 0, "Menu", False, "Enter select • Esc back", alert="Press Esc again to quit"))
        self.assertLessEqual(len(lines), 8)
        self.assertIn("Row 0", "\n".join(lines))


class ProfileAndPreviewTests(unittest.TestCase):
    def test_a_failed_rewrite_keeps_the_picture_the_profile_names(self):
        import tempfile
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        with patch.dict(terminal_profile.os.environ, {"LOCALAPPDATA": folder.name}), \
             patch.object(terminal_profile, "supported", return_value=True), \
             patch.object(terminal_profile, "font_installed", return_value=False):
            terminal_profile.write(theme.THEMES["citrinitas"], "dore-satan")
            replace = Path.replace

            def fail_on_the_fragment(self, target):
                if str(target).endswith(".json"):
                    raise OSError("disk full")
                return replace(self, target)

            with patch.object(Path, "replace", new=fail_on_the_fragment), self.assertRaises(OSError):
                terminal_profile.write(theme.THEMES["citrinitas"], "dore-raven")
            named = json.loads(terminal_profile.fragment_path().read_text(encoding="utf-8"))
            picture = named["profiles"][0]["backgroundImage"]
            self.assertTrue((terminal_profile.folder() / picture).is_file())

    def test_the_update_preview_does_not_read_saved_settings(self):
        args = SimpleNamespace(theme=None, preview_update="success")
        with patch.object(appearance, "saved", side_effect=AssertionError("settings were read")):
            main._apply_appearance(args)
        self.assertEqual(theme.PALETTE.key, theme.DEFAULT_THEME)


class AppearanceBackTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)
        theme.apply("citrinitas", focus="bar", density="comfortable")

    def test_back_after_a_preview_puts_the_applied_colours_back(self):
        screen = Console(file=io.StringIO(), width=100, height=40, color_system=None)
        with patch.object(selector, "console", screen), \
             patch.object(selector, "_render", return_value=True), \
             patch.object(selector.sys, "stdout", io.StringIO()), \
             patch.object(selector.readchar, "readkey", side_effect=[K.DOWN, " ", K.END, K.ENTER]):
            appearance.appearance_menu()
        self.assertEqual(theme.PALETTE.key, "citrinitas")


class SecondReviewTests(unittest.TestCase):
    """Found by the second outside review (GPT-6.1-Sol)."""

    def setUp(self):
        isolate_store(self)

    def test_the_status_line_counts_bookmarks_without_copying_them(self):
        from torrent_finder import bookmarks
        from torrent_finder.ui import chrome
        with patch.object(bookmarks, "entries", side_effect=AssertionError("copied every bookmark")):
            figures = dict(chrome._figures())
        self.assertEqual(figures["Bookmarks"], "0")

    def test_a_failed_network_check_leaves_no_old_verdict(self):
        from torrent_finder import security
        security._exposure["state"] = "vpn"
        self.addCleanup(security._exposure.update, state=None)
        with patch.object(security, "_fetch_network_info", return_value=None), \
             patch.object(security.readchar, "readkey", return_value="\x1b"), \
             patch.object(security.sys, "stdout", io.StringIO()), \
             patch.object(security, "console", Console(file=io.StringIO(), width=80, height=24)):
            security.show_security_warning(force=True)
        self.assertIsNone(security.exposure())
        self.assertEqual(security.exposure_label(), "")

    def test_a_painting_that_cannot_be_saved_is_still_used_this_session(self):
        with patch("torrent_finder.state.commit_setting", side_effect=OSError("disk full")),              self.assertRaises(OSError):
            appearance.save("citrinitas", "bar", "comfortable", "dore-raven")
        self.assertEqual(appearance.painting(), "dore-raven")

    def test_every_accepted_upload_time_can_be_shown(self):
        from datetime import datetime, timezone
        from torrent_finder.result_view import timestamp
        for value in (253402300799, "9999-12-31T23:59:59+00:00", 32536850399, 1700000000, "2024-01-02T03:04:05Z"):
            with self.subTest(value=value):
                datetime.fromtimestamp(timestamp(value), timezone.utc)  # never raises
        self.assertEqual(timestamp(1700000000), 1700000000)

    def test_the_baseline_also_applies_under_unittest(self):
        self.assertTrue(getattr(unittest.TestCase.run, "from_baseline", False))
        self.assertEqual(theme.PALETTE.key, "quiet")


class RoundTwoTests(unittest.TestCase):
    """Found in the second review round (GPT-6-Astra)."""

    def setUp(self):
        isolate_store(self)

    def test_a_slow_drive_does_not_hold_up_the_menu(self):
        from torrent_finder.ui import inspector
        started = time.monotonic()
        with patch.object(inspector.shutil, "disk_usage", side_effect=lambda path: time.sleep(2)):
            lines = [line.plain for line in inspector.download_folder(".")]
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertFalse(any("Free" in line for line in lines))
        self.assertTrue(any("Unpack" in line for line in lines))

    def test_recent_searches_do_not_expand_the_whole_history(self):
        from torrent_finder import state
        from torrent_finder.ui import inspector
        for query in ("one", "two", "three", "four"):
            state.add_history_entry(query, "movies")
        with patch.object(state, "load_history", side_effect=AssertionError("expanded every entry")):
            self.assertEqual([entry["query"] for entry in inspector._recent("movies")], ["four", "three", "two"])
            self.assertEqual([entry["query"] for entry in inspector._recent(skip=1, limit=2)], ["three", "two"])

    def test_a_saved_query_with_line_breaks_stays_one_row(self):
        NEWLINE = chr(10)
        BROKEN = "Part one" + NEWLINE + "Part two"
        items = [SelectItem("Row", "row", description="Help.",
                            inspect=lambda: [Text(f"line {i}") for i in range(30)] + [Text(BROKEN)]),
                 SelectItem(BROKEN, "q", description="Help.")]
        for design in ("quiet", "citrinitas"):
            theme.apply(design)
            for cursor in (0, 1):
                with self.subTest(design=design, cursor=cursor):
                    screen = Console(file=io.StringIO(), width=150, height=24, color_system=None)
                    with patch.object(selector, "console", screen):
                        screen.print(selector._build_panel(items, cursor, "Menu", False))
                    self.assertLessEqual(len(screen.file.getvalue().rstrip(NEWLINE).split(NEWLINE)), 24)

    def test_the_key_list_is_not_drawn_over(self):
        size = [ConsoleDimensions(80, 24)]
        drawn = []

        def keys_list(title, footer):
            before = len(drawn)
            size[0] = ConsoleDimensions(100, 30)
            time.sleep(0.4)
            drawn.append(("during", len(drawn) - before))

        keys = iter(["?", K.ESC])
        with patch.object(type(selector.console), "size", property(lambda _self: size[0])), \
             patch.object(selector, "_render", side_effect=lambda *a, **k: drawn.append("frame") or True), \
             patch.object(selector, "show_keys", side_effect=keys_list), \
             patch.object(selector.sys, "stdout", io.StringIO()), \
             patch.object(selector.readchar, "readkey", side_effect=lambda: next(keys)):
            selector.arrow_select([SelectItem("Row")], title="Menu")
        self.assertIn(("during", 0), drawn)

    def test_a_text_field_without_a_message_line_leaves_the_message_waiting(self):
        from torrent_finder.ui import chrome
        theme.apply("citrinitas", focus="bar", density="comfortable")
        chrome.clear_messages()
        self.addCleanup(chrome.clear_messages)
        chrome.announce("A raven arrives.")
        screen = Console(file=io.StringIO(), width=80, height=12, color_system=None)
        with patch.object(prompts, "console", screen), \
             patch.object(prompts.sys, "stdout", io.StringIO()), \
             patch.object(prompts.readchar, "readkey", side_effect=[K.ESC]):
            prompts.get_query_with_shortcut(prompts.PROMPT, screen_renderer=prompts.input_screen("Name"))
        self.assertEqual(chrome.take_message(), "A raven arrives.")


class SecondRoundSolTests(unittest.TestCase):
    """Found in the second review round (GPT-6.1-Sol)."""

    def setUp(self):
        isolate_store(self)

    def provider(self):
        engines = [SimpleNamespace(name="Nyaa", mode="on", description="")]
        return SimpleNamespace(slug="anime", engines=engines, active_presets=[], preferred_presets=[])

    def test_unreadable_stats_leave_the_rest_of_the_pane(self):
        from torrent_finder.ui import inspector
        for stats in ({"searches_by_provider": None}, {"searches_by_provider": {"anime": "x"}}, None):
            with self.subTest(stats=stats), patch("torrent_finder.stats.get_all_stats", return_value=stats):
                lines = [line.plain for line in inspector.provider(self.provider())]
            self.assertEqual(lines[0], "ENGINES")
            self.assertNotIn("THIS SHELF", lines)

    def test_continue_names_a_combined_search_providers_and_keywords(self):
        from torrent_finder.ui import inspector
        entry = {"query": "dune", "provider": "all", "timestamp": "2026-10-05T10:00:00+00:00",
                 "search_profile": {"selected": ["anime", "books"],
                                    "shared": {"include_keywords": ["1080p"], "exclude_keywords": []}}}
        lines = [line.plain for line in inspector.continue_search(entry)]
        self.assertTrue(any(line.startswith("  Providers") and "Anime" in line and "Books" in line for line in lines))
        self.assertIn("  Include     1080p", lines)
        self.assertFalse(any("Exclude" in line for line in lines))

    def test_a_relative_folder_not_made_yet_reports_its_drive(self):
        from torrent_finder.ui import inspector
        asked = []
        with patch.object(inspector.shutil, "disk_usage",
                          side_effect=lambda path: asked.append(path) or SimpleNamespace(free=1, total=2)):
            lines = [line.plain for line in inspector.download_folder("not-made-yet/sub")]
        self.assertTrue(asked and Path(asked[0]).is_absolute())
        self.assertTrue(any("Free" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
