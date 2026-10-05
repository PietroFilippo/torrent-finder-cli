"""The main menu's sections, hints and status; the Continue row; the Appearance picker."""

import io
import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirects saved settings before anything reads them
from isolation import isolate_store
from readchar import key as K
from rich.console import Console
from rich.text import Text

from torrent_finder import main, security, state
from torrent_finder.providers import get_provider
from torrent_finder.ui import appearance, prompts, selector, theme


def capture_home(**kwargs):
    captured = []
    with patch.object(prompts, "arrow_select", side_effect=lambda items, **kw: captured.append((items, kw))):
        prompts.provider_select_prompt(**kwargs)
    return captured[0]


def section_labels(items):
    return [item.label for item in items if item.value == "section_header"]


class HomeTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)
        self.addCleanup(security._exposure.update, state=None)

    def test_sections_and_the_continue_row(self):
        items, kw = capture_home()
        self.assertEqual(section_labels(items), ["Search", "Tools"])  # no history yet
        state.add_history_entry("dune part two", "movies")
        items, kw = capture_home()
        self.assertEqual(section_labels(items), ["Continue", "Search", "Tools"])
        row = items[1]
        self.assertEqual((row.label, row.value[0]), ("dune part two", "continue"))
        self.assertIn("Movies & Series", row.hint)
        self.assertEqual(kw["start_index"], 1)  # the cursor starts on it

    def test_entries_the_field_cannot_hold_replay_like_history(self):
        state.add_history_entry("Frieren", "anime", queries=["Frieren", "Sousou no Frieren"])
        items, _ = capture_home()
        self.assertEqual(items[1].value[0], "history")
        self.assertIn("2 names", items[1].hint)

    def test_provider_rows_say_what_they_search(self):
        movies = get_provider("movies")
        preset = next(p for p in movies.presets if p.name == "1080p")
        movies.preferred_presets.append(preset)
        self.addCleanup(movies.preferred_presets.clear)
        items, _ = capture_home()
        hint = next(item.hint for item in items if item.value is movies)
        engines = ", ".join(engine.name for engine in movies.effective_engines)
        self.assertEqual(hint.plain, f"{engines} · Prefer 1080p")
        prefer = hint.plain.index("Prefer")
        self.assertTrue(any(span.start == prefer and str(span.style) == theme.ACCENT for span in hint.spans))
        games = next(item for item in items if item.label == "Games")
        self.assertEqual(games.hint.plain, "General, Online-Fix, FitGirl")
        credentials = next(item for item in items if item.value == "__credentials__")
        self.assertRegex(credentials.hint, r"^\d+ of \d+ set$")

    def test_the_header_names_version_update_and_network(self):
        _, kw = capture_home(update_available=True, update_status="update 9.9.9 ready")
        status = Text.from_markup(kw["status"]()).plain
        self.assertTrue(status.startswith("v"))
        self.assertIn("update 9.9.9 ready", status)
        self.assertNotIn("IP visible", status)  # no check ran this session
        security._exposure["state"] = "exposed"
        self.assertIn("IP visible", Text.from_markup(kw["status"]()).plain)
        security._exposure["state"] = "vpn"
        self.assertIn("VPN", Text.from_markup(kw["status"]()).plain)

    def test_f_ignores_rows_that_are_not_providers(self):
        state.add_history_entry("dune", "movies")
        items, kw = capture_home()
        handle_f = kw["key_actions"]["f"]
        self.assertIs(handle_f(1, items), True)  # the continue row
        games = next(i for i, item in enumerate(items) if item.label == "Games")
        self.assertIs(handle_f(games, items), True)
        movies = next(i for i, item in enumerate(items) if item.label == "Movies & Series")
        self.assertEqual(handle_f(movies, items), movies)

    def test_the_menu_fits_common_windows_with_the_cursor_shown(self):
        state.add_history_entry("dune part two", "movies")
        items, kw = capture_home(update_available=True, update_status="update 9.9.9 ready")
        for width, height in ((40, 12), (50, 16), (80, 24), (120, 40)):
            with self.subTest(width=width, height=height):
                screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
                with patch.object(selector, "console", screen), patch.object(prompts, "console", screen):
                    screen.print(selector._build_panel(items, 1, kw["title"], False, kw["footer"](),
                                                       status=kw["status"]()))
                lines = screen.file.getvalue().rstrip("\n").split("\n")
                self.assertLessEqual(len(lines), height)
                self.assertIn(theme.CURSOR + " dune part two", "\n".join(lines))

    def test_continue_opens_the_search_field_with_the_query(self):
        entry = {"query": "dune part two", "provider": "movies", "timestamp": "2026-10-01T09:30:00+00:00"}
        seen = []

        def field(_prompt, **kwargs):
            seen.append((kwargs["initial"], kwargs["screen_renderer"]))
            raise KeyboardInterrupt  # Ctrl+C at the field: back to the menu, quit armed

        with patch("sys.argv", ["torrent", "-y"]), \
             patch.object(main, "advise_limited_terminal"), \
             patch.object(main, "check_for_update", return_value=None), \
             patch.object(main, "consume_update_report", return_value=None), \
             patch.object(main, "console"), \
             patch.object(main, "clear_screen"), \
             patch.object(main, "provider_select_prompt", side_effect=[("continue", entry), None]), \
             patch.object(main, "get_query_with_shortcut", side_effect=field), \
             patch.object(main, "_goodbye") as goodbye:
            main._main_loop()
        self.assertEqual(seen[0][0], "dune part two")
        goodbye.assert_called_once()

    def test_a_submenu_disarms_the_quit_guard(self):
        guard = prompts.QuitGuard(armed=True)
        hints = []

        def menu(items, **kw):
            hints.append(kw["alert"]())
            if len(hints) == 1:
                return next(i for i, item in enumerate(items) if item.value == "__settings__")
            return None

        with patch.object(prompts, "arrow_select", side_effect=menu), patch.object(prompts, "settings_menu"):
            self.assertIsNone(prompts.provider_select_prompt(quit_guard=guard))
        self.assertEqual(hints, ["[alert]Press Esc or Ctrl+C again to quit[/alert]", ""])
        self.assertFalse(guard.armed)  # the next Esc only arms it again

    def test_the_tip_is_passed_for_the_bottom_rows(self):
        items, kwargs = capture_home()
        self.assertTrue(kwargs["tip"].startswith("[accent]Tip[/accent]"))
        self.assertNotIn("Tip", kwargs["footer"]())  # no longer above the keys

    def test_settings_gathers_appearance_command_and_network(self):
        captured = []
        with patch.object(prompts, "arrow_select", side_effect=lambda items, **kw: captured.append(items)):
            prompts.settings_menu()
        values = [item.value for item in captured[0]]
        self.assertEqual(values, ["appearance", "__terminal_command__", "__network_info__", None])
        self.assertIn("Quiet Blue", captured[0][0].hint)


class AppearanceMenuTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)
        self.addCleanup(theme.apply, "quiet", focus="bar", density="comfortable")  # the suite's baseline

    def run_menu(self, keys):
        screen = Console(file=io.StringIO(), width=100, height=40, color_system=None)
        # Frames are built but not written: Rich caches a style's escape codes
        # on first render, and a 16-colour write here would leak into later
        # true-colour tests.
        with patch.object(selector, "console", screen), \
             patch.object(selector, "_render", return_value=True), \
             patch.object(selector.sys, "stdout", io.StringIO()), \
             patch.object(selector.readchar, "readkey", side_effect=keys):
            appearance.appearance_menu()

    def test_space_previews_and_esc_puts_the_saved_theme_back(self):
        self.run_menu([K.DOWN, " ", K.ESC])
        self.assertEqual(theme.PALETTE.key, "quiet")
        self.assertIsNone(state.load_setting(appearance.SETTING))  # a preview saves nothing

    def test_enter_applies_and_saves_the_theme(self):
        self.run_menu([K.DOWN, K.ENTER, K.ESC])  # Quiet Blue → Iris
        self.assertEqual(theme.PALETTE.key, "iris")
        self.assertEqual(appearance.saved(), {"theme": "iris", "focus": "bar", "density": "comfortable",
                                              "painting": "dore-satan"})

    def test_focus_and_density_rows_apply_and_save(self):
        # From Quiet Blue: five themes down, past the Focus heading to Filled row, then Compact.
        self.run_menu([K.DOWN] * 7 + [K.ENTER] + [K.DOWN] * 2 + [K.ENTER, K.ESC])
        self.assertEqual(theme.current()[1:], ("fill", "compact"))
        self.assertEqual(appearance.saved(), {"theme": "quiet", "focus": "fill", "density": "compact",
                                              "painting": "dore-satan"})

    def test_every_theme_row_shows_its_own_colours(self):
        for design, current in (("simple", "quiet"), ("athanor", "citrinitas")):
            theme.apply(current)
            captured = []
            with patch("torrent_finder.ui.selector.arrow_select",
                       side_effect=lambda items, **kw: captured.append(items)):
                appearance.appearance_menu()
            items = captured[0]
            designs = [item.label for item in items if isinstance(item.value, tuple) and item.value[0] == "design"]
            self.assertEqual(designs, ["Athanor", "Simple"])
            rows = {item.label: item for item in items if isinstance(item.value, tuple) and item.value[0] == "theme"}
            self.assertEqual(list(rows), [palette.name for palette in theme.palettes(design)])  # only its own design
            for palette in theme.palettes(design):
                styles = {str(span.style) for span in rows[palette.name].hint.spans}
                self.assertIn(palette.accent, styles)
                self.assertIn(f"bold {palette.sky}", styles)
            self.assertEqual(rows[theme.THEMES[current].name].marker, "●")

    def test_choosing_a_design_starts_on_its_default_colours(self):
        # From Quiet Blue (Simple): up past the colours heading to Simple, then up to Athanor.
        self.run_menu([K.UP, K.UP, K.ENTER, K.ESC])
        self.assertEqual(theme.PALETTE.key, "citrinitas")
        self.assertTrue(theme.FRAMED)
        self.assertEqual(appearance.saved()["theme"], "citrinitas")
        self.run_menu([K.DOWN, K.ENTER, K.ESC])  # Citrinitas → Rubedo keeps the Athanor design
        self.assertEqual(theme.PALETTE.design, "athanor")
        self.assertEqual(theme.PALETTE.key, "rubedo")

    def test_the_screen_says_themes_leave_the_background_to_the_terminal(self):
        captured = {}
        with patch("torrent_finder.ui.selector.arrow_select", side_effect=lambda items, **kw: captured.update(kw, items=items)):
            appearance.appearance_menu()
        self.assertIn(appearance.BACKGROUND_NOTE, captured["footer"]())
        rows = {item.label: item for item in captured["items"]}
        self.assertIn("light colour scheme", rows["Paper"].description)  # only the light theme says how
        self.assertIn(appearance.light_scheme_help(), rows["Paper"].description)
        self.assertNotIn("colour scheme", rows["Iris"].description)
        self.assertIn("Windows Terminal: Ctrl+,", appearance.light_scheme_help("win32"))
        self.assertIn("iTerm2", appearance.light_scheme_help("darwin"))
        self.assertIn("preferences", appearance.light_scheme_help("linux"))


if __name__ == "__main__":
    unittest.main()
