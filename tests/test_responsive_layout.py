import io
import re
import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from rich.cells import cell_len
from rich.console import Console

from torrent_finder.ui import selector, streaming, table
from torrent_finder.ui.selector import SelectItem


def _render(renderable, width, height=40):
    buffer = io.StringIO()
    console = Console(
        file=buffer,
        width=width,
        height=height,
        record=True,
        color_system=None,
        force_terminal=False,
    )
    console.print(renderable)
    output = console.export_text(styles=False)
    for line in output.splitlines():
        if line:
            assert cell_len(line) <= width, (width, cell_len(line), line)
    return output


class ResponsiveSelectorTests(unittest.TestCase):
    def test_narrow_selector_wraps_complete_description_footer_and_hint(self):
        narrow = Console(width=48, height=20, color_system=None)
        items = [
            SelectItem(
                label="A selectable row with a deliberately long label",
                value="row",
                hint="installation hint reaches HINT-END",
                description=(
                    "This description must remain readable in a narrow terminal "
                    "instead of being cropped at DESCRIPTION-END"
                ),
            ),
            SelectItem(label="Go back", value="back", is_action=True),
        ]
        footer = (
            "Use arrows to navigate while this complete footer remains available "
            "through FOOTER-END"
        )

        with patch.object(selector, "console", narrow):
            panel = selector._build_panel(items, 0, "Responsive", False, footer)

        output = _render(panel, 48, 20)
        self.assertIn("HINT-END", output)
        self.assertIn("DESCRIPTION-END", output)
        self.assertIn("FOOTER-END", output)
        self.assertLessEqual(len(output.splitlines()), 20)


class ResponsiveTableTests(unittest.TestCase):
    RESULTS = [
        {
            "name": "A very long release name that needs a responsive name column",
            "source": "Nyaa",
            "from_work": "Example Work",
            "size": 2_500_000_000,
            "seeders": 42,
            "leechers": 7,
        }
    ]

    def _table(self, width):
        sized_console = Console(width=width, height=30, color_system=None)
        with patch.object(table, "console", sized_console):
            return table.build_table(
                self.RESULTS,
                selected_idx=0,
                scroll_offset=0,
                visible_count=1,
                total=1,
                show_from=True,
            )

    def test_table_uses_progressive_columns(self):
        self.assertEqual(
            [column.header for column in self._table(140).columns],
            ["Sel", "#", "Source", "From", "Name", "Size", "Seeds", "Leeches"],
        )
        self.assertEqual(
            [column.header for column in self._table(100).columns],
            ["Sel", "#", "Source", "Name", "Size", "Seeds"],
        )
        self.assertEqual(
            [column.header for column in self._table(72).columns],
            ["Sel", "#", "Name", "Seeds"],
        )
        self.assertEqual(
            [column.header for column in self._table(46).columns],
            ["Result"],
        )

    def test_narrow_table_preserves_hidden_selected_metadata(self):
        responsive_table = self._table(72)

        output = _render(responsive_table, 72)
        self.assertIn("Source: Nyaa", output)
        self.assertIn("From: Example Work", output)
        self.assertIn("Leeches: 7", output)
    def test_each_table_layout_stays_inside_its_terminal_width(self):
        for width in (140, 100, 72, 46):
            with self.subTest(width=width):
                _render(self._table(width), width)


class ResponsiveCellWidthTests(unittest.TestCase):
    def test_streaming_truncation_uses_terminal_cells_not_python_length(self):
        truncated = streaming._truncate("界" * 20, 10)

        self.assertLessEqual(cell_len(truncated), 10)
        self.assertTrue(truncated.endswith("…"))
    def test_stream_scroll_region_starts_below_wrapped_header(self):
        rendered = io.StringIO()
        terminal = io.StringIO()
        narrow = Console(
            file=rendered,
            width=48,
            height=60,
            color_system=None,
            force_terminal=False,
        )

        with (
            patch.object(streaming, "console", narrow),
            patch.object(streaming, "_clear_terminal"),
            patch.object(streaming.sys, "stdout", terminal),
        ):
            streaming._print_stream_header(
                ep_idx=0,
                total=2,
                file_idx=1,
                multi=True,
                use_scroll_region=True,
                sub_paths=["a subtitle filename that also needs wrapping.srt"],
                backend="peerflix",
                filename="a deliberately long streaming filename that wraps.mkv",
                filesize_bytes=2_500_000_000,
            )

        region = re.search(r"\x1b\[(\d+);60r", terminal.getvalue())
        self.assertIsNotNone(region)
        self.assertGreater(int(region.group(1)), streaming._STREAM_HEADER_LINES + 1)


if __name__ == "__main__":
    unittest.main()
