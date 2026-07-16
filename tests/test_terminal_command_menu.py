import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from torrent_finder.launcher_alias import LauncherStatus
from torrent_finder.ui import launcher, prompts


class TerminalCommandMenuTests(unittest.TestCase):
    def test_selector_exposes_only_the_fixed_command_presets(self):
        items = launcher._command_items("tf", available=True)

        self.assertEqual(
            [item.value for item in items],
            ["torrent-finder", "tf", "torrent", "find-torrent", "tfind", "back"],
        )
        self.assertIn("current", items[1].hint)

    def test_selecting_preset_calls_launcher_service(self):
        current = LauncherStatus("torrent-finder", available=True, path_ready=True)
        installed = LauncherStatus(
            "tf", path="C:/bin/tf.cmd", managed=True, available=True, path_ready=True
        )

        with patch.object(launcher, "current_status", return_value=current), \
             patch.object(launcher, "arrow_select", side_effect=[1, None]), \
             patch.object(launcher, "set_terminal_command", return_value=installed) as set_command:
            launcher.terminal_command_prompt()

        set_command.assert_called_once_with("tf")

    def test_startup_provider_menu_contains_terminal_command_row(self):
        captured = {}

        def capture(items, **_kwargs):
            captured["items"] = items
            return None

        with patch.object(prompts, "arrow_select", side_effect=capture), \
             patch("torrent_finder.launcher_alias.current_status", return_value=LauncherStatus("tf", available=True)):
            result = prompts.provider_select_prompt()

        self.assertIsNone(result)
        values = [item.value for item in captured["items"]]
        self.assertIn("__terminal_command__", values)


if __name__ == "__main__":
    unittest.main()
