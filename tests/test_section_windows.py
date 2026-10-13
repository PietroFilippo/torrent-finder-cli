"""Windowed lists keep section headings with their rows: none ends a page, and a page inside a section repeats its heading."""

import io
import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirects saved settings before anything reads them
from rich.console import Console

from torrent_finder.ui import selector, theme
from torrent_finder.ui.selector import SelectItem

KEYS = "↑/↓ navigate  •  Enter select  •  Esc back"
SECTIONS = {"Design": 2, "Colours": 5, "Painting": 11, "Font": 5, "Focus": 2, "Density": 2}


def menu() -> list[SelectItem]:
    items = []
    for name, count in SECTIONS.items():
        items.append(SelectItem(f"─── {name} ───", "section_header", enabled=False, is_action=True))
        items += [SelectItem(f"{name} {i}", (name, i)) for i in range(1, count + 1)]
    items.append(SelectItem("Back", None, is_action=True))
    return items


def frame(items, cursor, width, height) -> list[str]:
    screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
    with patch.object(selector, "console", screen):
        screen.print(selector._build_panel(items, cursor, "Appearance", False, KEYS))
    return screen.file.getvalue().rstrip("\n").split("\n")


def list_rows(lines: list[str]) -> list[str]:
    """The rows of the list: headings (upper case) and items, as drawn, up to the Back row."""
    rows = []
    for line in lines:
        text = line.strip("║ ")
        if text in {name.upper() for name in SECTIONS} or any(text.lstrip("@▍ ").startswith(f"{n} ") for n in SECTIONS):
            rows.append(text)
        if text.lstrip("@▍ ") == "Back":
            break
    return rows


class SectionWindowTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(theme.apply, "quiet", focus="bar", density="comfortable")

    def test_no_page_ends_on_a_heading_and_the_cursor_always_shows(self):
        for design in ("quiet", "citrinitas"):
            theme.apply(design, focus="bar", density="comfortable")
            items = menu()
            for height in (12, 16, 20, 24, 36):
                for cursor in [i for i, item in enumerate(items) if item.enabled]:
                    with self.subTest(design=design, height=height, cursor=cursor):
                        lines = frame(items, cursor, 100, height)
                        rows = list_rows(lines)
                        self.assertTrue(rows)
                        last = rows[-1]
                        self.assertFalse(last.isupper() and last.title() in SECTIONS, f"page ends on {last!r}")
                        label = items[cursor].label
                        self.assertTrue(any(label in line for line in lines), f"{label!r} is off the page")
                        self.assertLessEqual(len(lines), height)

    def test_a_page_that_starts_inside_a_section_repeats_its_heading(self):
        theme.apply("quiet", focus="bar", density="comfortable")
        items = menu()
        cursor = next(i for i, item in enumerate(items) if item.label == "Painting 9")
        rows = list_rows(frame(items, cursor, 100, 16))
        self.assertEqual(rows[0], "PAINTING")
        self.assertTrue(rows[1].lstrip("▍ ").startswith("Painting "))
        self.assertEqual(sum(row == "PAINTING" for row in rows), 1)

    def test_a_heading_cut_from_the_end_opens_the_next_page(self):
        items = menu()
        painting = next(i for i, item in enumerate(items) if item.label == "─── Painting ───")
        # A window ending on the PAINTING heading: at the top of the list it loses that row...
        self.assertEqual(selector._section_window(items, 0, len(items) - 1, 0, painting + 1, 1),
                         (0, painting, None))
        # ...and lower down it moves up a row instead, keeping its height.
        self.assertEqual(selector._section_window(items, 0, len(items) - 1, 1, painting + 1, 2)[:2],
                         (0, painting))

    def test_a_short_list_is_untouched(self):
        theme.apply("quiet", focus="bar", density="comfortable")
        items = menu()[:9]  # Design and Colours only
        rows = list_rows(frame(items, 1, 100, 30))
        self.assertEqual(rows[0], "DESIGN")
        self.assertEqual(len(rows), 9)

    def test_the_window_helper_keeps_the_cursor(self):
        items = menu()
        for start in range(0, 20):
            for rows in (2, 4, 6):
                for cursor in range(start, start + rows):
                    if not items[cursor].enabled:
                        continue
                    with self.subTest(start=start, rows=rows, cursor=cursor):
                        s, e, heading = selector._section_window(items, 0, len(items) - 1, start, start + rows,
                                                                 cursor)
                        self.assertTrue(s <= cursor < e)
                        self.assertLessEqual(e - s + (1 if heading is not None else 0), rows)
                        if e < len(items) - 1:
                            self.assertFalse(selector._is_section_header(items[e - 1]))
                        if heading is not None:
                            self.assertTrue(selector._is_section_header(items[heading]))
                            self.assertLess(heading, s)


if __name__ == "__main__":
    unittest.main()
