import io
import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from rich.console import Console

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from torrent_finder.ui import prompts


class SearchPromptShortcutTests(unittest.TestCase):
    def test_main_restores_multi_title_draft_after_actions_and_filters(self):
        from torrent_finder import main
        from isolation import isolate_store
        isolate_store(self)
        seen = []
        def field(_prompt, **kwargs):
            seen.append((kwargs["initial"], kwargs.get("initial_committed")))
            if len(seen) == 1:
                return ("ACTIONS", "current", ["first", "second"])
            if len(seen) == 2:
                return ("FILTERS", "edited", ["first", "second"])
            raise KeyboardInterrupt
        with patch("sys.argv", ["torrent", "-y", "-t", "anime"]), \
             patch.object(main, "advise_limited_terminal"), \
             patch.object(main, "check_for_update", return_value=None), \
             patch.object(main, "consume_update_report", return_value=None), \
             patch.object(main, "console"), patch.object(main, "clear_screen"), \
             patch.object(main, "provider_select_prompt", return_value=None), \
             patch.object(main, "get_query_with_shortcut", side_effect=field), \
             patch.object(main, "_quick_actions_flow", return_value=None) as actions, \
             patch.object(main, "filter_menu") as filters, patch.object(main, "_goodbye"):
            main._main_loop()
        self.assertEqual(seen[1:], [("current", ["first", "second"]), ("edited", ["first", "second"])])
        self.assertEqual(actions.call_args.args[2], "current")
        filters.assert_called_once()

    def test_shortcuts_show_filters_then_multi_title_then_actions(self):
        line = prompts.search_shortcuts_line(has_history=False)

        self.assertLess(line.index("Ctrl+F"), line.index("Ctrl+N"))
        self.assertLess(line.index("Ctrl+N"), line.index("Tab"))

    def test_resize_owned_editor_preserves_multi_title_input_and_restores_screen(self):
        terminal = io.StringIO()
        sized_console = Console(
            file=io.StringIO(), width=72, height=18, color_system=None
        )
        keys = [
            "a",
            prompts.readchar.key.CTRL_N,
            "b",
            prompts.readchar.key.ENTER,
        ]

        with (
            patch.object(prompts, "console", sized_console),
            patch.object(prompts.sys, "stdout", terminal),
            patch.object(prompts.readchar, "readkey", side_effect=keys),
        ):
            result = prompts.get_query_with_shortcut(
                "[title] Search:[/title] ",
                multi=True,
                screen_renderer=lambda target: target.print("Header"),
            )

        self.assertEqual(result, ["a", "b"])
        self.assertTrue(terminal.getvalue().startswith("\033[?1049h"))
        self.assertTrue(terminal.getvalue().endswith("\033[?25h\033[?1049l"))


if __name__ == "__main__":
    unittest.main()
