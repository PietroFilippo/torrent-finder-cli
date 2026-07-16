import io
import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from rich.console import Console

from torrent_finder.ui import prompts


class SearchPromptShortcutTests(unittest.TestCase):
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