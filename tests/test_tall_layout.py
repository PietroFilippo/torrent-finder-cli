"""Tall windows: the key bar sits at the bottom, and the focused row's details fill rows the list leaves empty."""

import io
import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirects saved settings before anything reads them
from rich.console import Console
from rich.text import Text

from torrent_finder.ui import selector, theme
from torrent_finder.ui.selector import SelectItem

KEYS = "↑/↓ navigate  •  Enter select  •  Esc back"


def frame(items, cursor, width, height, **kwargs) -> list[str]:
    screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
    with patch.object(selector, "console", screen):
        screen.print(selector._build_panel(items, cursor, "Settings", False, KEYS, **kwargs))
    return screen.file.getvalue().rstrip("\n").split("\n")


def menu(details=()) -> list[SelectItem]:
    return [SelectItem("Appearance", "appearance", hint="Citrinitas", description="Theme colours and spacing.",
                       inspect=(lambda: [Text(line) for line in details]) if details else None),
            SelectItem("Terminal command", "command", description="A quick-launch command."),
            SelectItem("Back", None, is_action=True)]


def row_of(lines: list[str], text: str) -> int:
    return next(i for i, line in enumerate(lines) if text in line)


class FooterTests(unittest.TestCase):
    def test_a_short_list_keeps_its_place_and_the_keys_go_to_the_bottom(self):
        for design in ("quiet", "citrinitas"):
            with self.subTest(design=design):
                theme.apply(design, focus="bar", density="comfortable")
                lines = frame(menu(), 0, 100, 40)
                self.assertLessEqual(row_of(lines, "Appearance"), 3)
                keys = row_of(lines, "Enter select")
                self.assertGreaterEqual(keys, 33)  # the last rows, above the Athanor frame's bottom lines
                self.assertLess(row_of(lines, "Back"), row_of(lines, "Theme colours and spacing.") - 5)
                self.assertEqual(row_of(lines, "Theme colours and spacing."), keys - 2)  # help, rule, keys

    def test_the_tip_stays_on_the_last_rows_below_the_keys(self):
        theme.apply("quiet", focus="bar", density="comfortable")
        lines = frame(menu(), 0, 100, 40, tip="[muted]Tip[/muted]  Press S for stats.")
        self.assertEqual(row_of(lines, "Press S for stats."), len(lines) - 1)
        self.assertLess(row_of(lines, "Enter select"), len(lines) - 2)
        self.assertGreater(row_of(lines, "Enter select"), 30)

    def test_compact_density_and_short_windows_keep_the_keys_under_the_list(self):
        theme.apply("quiet", focus="bar", density="compact")
        lines = frame(menu(), 0, 100, 40)
        self.assertLess(row_of(lines, "Enter select"), 10)
        theme.apply("quiet", focus="bar", density="comfortable")
        lines = frame(menu(), 0, 100, 12)  # under the roomy threshold
        self.assertLess(row_of(lines, "Enter select"), 10)

    def test_a_wide_window_puts_the_keys_under_the_list_column(self):
        theme.apply("quiet", focus="bar", density="comfortable")
        lines = frame(menu(), 0, 200, 40)
        keys = row_of(lines, "Enter select")
        self.assertGreaterEqual(keys, 37)
        divider = lines[keys].index("│")
        self.assertLess(lines[keys].index("Enter select"), divider)  # the left column's bottom


class DetailsBelowTests(unittest.TestCase):
    DETAILS = ["APPEARANCE", "  Design      Athanor · Citrinitas", "  Focus       Cursor bar"]

    def setUp(self):
        theme.apply("quiet", focus="bar", density="comfortable")

    def test_a_tall_narrow_window_shows_the_details_above_the_keys(self):
        lines = frame(menu(self.DETAILS), 0, 100, 40)
        self.assertLess(row_of(lines, "Theme colours"), row_of(lines, "APPEARANCE"))
        self.assertLess(row_of(lines, "Focus       Cursor bar"), row_of(lines, "Enter select"))
        self.assertTrue(lines[row_of(lines, "APPEARANCE")].startswith(theme.MARGIN + "APPEARANCE"))

    def test_details_never_cost_list_rows(self):
        many = [SelectItem(f"Row {n}", n) for n in range(30)]
        items = menu([f"detail {n}" for n in range(40)]) + many
        lines = frame(items, 0, 100, 40)
        self.assertIn("Row 29", "\n".join(lines))  # every row still shows
        self.assertNotIn("detail 39", "\n".join(lines))
        lines = frame(menu([f"detail {n}" for n in range(40)]), 0, 100, 40)
        self.assertIn("detail 0", "\n".join(lines))
        self.assertEqual(lines[row_of(lines, "Enter select") - 2].strip(), "…")  # cut short above the rule

    def test_wide_windows_keep_them_in_the_pane_and_short_ones_leave_them_out(self):
        wide = frame(menu(self.DETAILS), 0, 200, 40)
        divider = wide[row_of(wide, "APPEARANCE")].index("│")
        self.assertGreater(wide[row_of(wide, "APPEARANCE")].index("APPEARANCE"), divider)
        self.assertNotIn("APPEARANCE", "\n".join(frame(menu(self.DETAILS), 0, 100, 12)))


if __name__ == "__main__":
    unittest.main()
