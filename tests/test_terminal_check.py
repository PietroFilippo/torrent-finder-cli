import unittest
import warnings
from unittest.mock import PropertyMock, patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from torrent_finder import terminal_check
from torrent_finder.constants import console


class TerminalCheckTests(unittest.TestCase):
    def test_noop_when_output_is_not_a_terminal(self):
        with patch.object(
            type(console), "is_terminal", new_callable=PropertyMock, return_value=False
        ):
            terminal_check.advise_limited_terminal()  # must not print or block

    def test_legacy_console_advisory_is_ascii_with_ready_commands(self):
        # The advisory targets the one console that garbles unicode, so the
        # rendered text must be plain ASCII and carry copy-paste-ready fixes.
        with patch.object(terminal_check, "readchar"), patch.object(
            type(console), "is_terminal", new_callable=PropertyMock, return_value=True
        ), patch.object(console, "legacy_windows", True):
            with console.capture() as capture:
                terminal_check.advise_limited_terminal()

        out = capture.get()
        self.assertIn("winget install -e --id Microsoft.WindowsTerminal", out)
        self.assertIn(
            "reg add HKCU\\Console /v VirtualTerminalLevel /t REG_DWORD /d 1 /f", out
        )
        self.assertTrue(out.isascii(), f"non-ASCII advisory: {out!r}")


if __name__ == "__main__":
    unittest.main()
