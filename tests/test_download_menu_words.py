"""The download menu says what each way out does, and a narrow window still shows the torrent's name."""

import io
import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirects saved settings before anything reads them
import readchar
from rich.text import Text

from torrent_finder.ui import display, prompts, selector, theme

MAGNET = "magnet:?xt=urn:btih:" + "ab" * 20
SHORT = {"name": "[SubsPlease] Frieren - 01 (1080p)", "size": 1_450_000_000, "seeders": 812, "leechers": 140,
         "source": "Nyaa", "uploaded_at": 1_789_000_000}
LONG = dict(SHORT, name="Dune.Part.Two.2024.2160p.UHD.BluRay.x265.HDR.DV.TrueHD.7.1-B0MBARDiERS")


def menu_frame(width: int, height: int, torrent: dict) -> list[str]:
    """The download menu's first frame at *width* x *height*, as plain text rows."""
    from rich.console import Console, ConsoleDimensions
    painted = []
    size = ConsoleDimensions(width, height)
    # Colourless frames: Rich keeps a style's first ANSI rendering, and the 16-colour fallback of an
    # off-screen console would stick to the palette's styles for the tests that follow.
    plain_console = lambda file, width, height=None: Console(file=file, width=width, height=height, color_system=None)  # noqa: E731
    with patch.object(type(selector.console), "size", property(lambda _self: size)), \
         patch.object(selector, "buffer_console", side_effect=plain_console), \
         patch.object(display, "paint", side_effect=lambda content, *a, **k: painted.append(content) or ""), \
         patch.object(selector.sys, "stdout", io.StringIO()), \
         patch.object(selector.readchar, "readkey", side_effect=[readchar.key.ESC]), \
         patch.object(prompts, "has_aria2", return_value=True), patch.object(prompts, "has_webtorrent", return_value=True), \
         patch.object(prompts, "has_peerflix", return_value=False), \
         patch.object(prompts, "detect_torrent_client", return_value="qBittorrent"):
        prompts.download_method_prompt(magnet=MAGNET, torrent=torrent, show_subtitles=True, show_episode_picker=True,
                                       page_url="https://nyaa.si/view/1", info_source="Nyaa")
    return [Text.from_ansi(line).plain for line in painted[0].split("\n")]


class WaysOutTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(theme.apply, "quiet", focus="bar", density="comfortable")

    def rows(self, menu):
        captured = {}

        def capture(items, **kwargs):
            captured["items"], captured["kwargs"] = items, kwargs
            return None

        with patch.object(prompts, "arrow_select", side_effect=capture), \
             patch.object(prompts, "has_aria2", return_value=True), \
             patch.object(prompts, "detect_torrent_client", return_value="qBittorrent"):
            menu()
        return captured["items"], captured["kwargs"]

    def test_the_single_menu_names_its_ways_out(self):
        items, kwargs = self.rows(lambda: prompts.download_method_prompt(magnet=MAGNET, torrent=SHORT))
        labels = [item.label for item in items]
        self.assertIn("Done with this torrent", labels)
        self.assertNotIn("Cancel", labels)
        done = next(item for item in items if item.value == "cancel")
        self.assertIn("what to do next", done.description)
        self.assertEqual(next(item for item in items if item.value == "back").label, "Back to results")
        self.assertIn("Esc back to results", kwargs["footer"])
        self.assertNotIn("cancel", kwargs["footer"])

    def test_the_batch_menu_names_its_ways_out(self):
        items, kwargs = self.rows(lambda: prompts.batch_download_menu(3, 3))
        self.assertEqual(next(item for item in items if item.value == "cancel").label, "Done with this selection")
        self.assertIn("Esc back to results", kwargs["footer"])


class NarrowWindowNameTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(theme.apply, "quiet", focus="bar", density="comfortable")

    def test_a_narrow_athanor_window_shows_the_name_under_the_cut_edge(self):
        theme.apply("citrinitas", focus="bar", density="comfortable")
        lines = menu_frame(40, 12, SHORT)
        self.assertNotIn(SHORT["name"], lines[0])  # the edge has room for "Down…" only
        self.assertTrue(any(SHORT["name"] in line for line in lines[1:]), "\n".join(lines))

    def test_a_long_name_appears_under_the_edge_at_80_columns_and_once_at_137(self):
        theme.apply("citrinitas", focus="bar", density="comfortable")
        lines = menu_frame(80, 24, LONG)
        self.assertNotIn(LONG["name"], lines[1])  # the top edge (the message line is row 0)
        self.assertTrue(any(LONG["name"] in line for line in lines[2:]))
        lines = menu_frame(137, 36, LONG)
        self.assertEqual(sum(LONG["name"] in line for line in lines), 1)  # the edge alone
        self.assertIn(LONG["name"], lines[1])

    def test_a_short_name_shows_once_when_the_header_has_room_for_it(self):
        for design, size in (("citrinitas", (137, 36)), ("quiet", (80, 24))):
            with self.subTest(design=design, size=size):
                theme.apply(design, focus="bar", density="comfortable")
                lines = menu_frame(*size, SHORT)
                self.assertEqual(sum(SHORT["name"] in line for line in lines), 1)

    def test_athanor_at_80_columns_keeps_the_name_readable_at_every_scroll_position(self):
        # The edge loses the name's end once the list's position ("10–23 of 23") takes its room, so
        # the name line shows whatever the position is.
        theme.apply("citrinitas", focus="bar", density="comfortable")
        lines = menu_frame(80, 24, SHORT)
        self.assertEqual(sum(SHORT["name"] in line for line in lines), 2)

    def test_simple_adds_the_name_when_its_second_header_line_is_cut(self):
        theme.apply("quiet", focus="bar", density="comfortable")
        for torrent in (SHORT, LONG):
            with self.subTest(name=torrent["name"]):
                lines = menu_frame(40, 12, torrent)
                self.assertTrue(any(torrent["name"][:34] in line for line in lines[2:]), "\n".join(lines))

    def test_header_shows_measures_the_edge(self):
        theme.apply("citrinitas", focus="bar", density="comfortable")
        title = f"Download › {SHORT['name']}"
        self.assertTrue(prompts.header_shows(SHORT["name"], title, 80, 24))
        self.assertFalse(prompts.header_shows(SHORT["name"], title, 40, 12))
        self.assertFalse(prompts.header_shows(SHORT["name"], title, 74, 24, rows=17))  # a position takes room


if __name__ == "__main__":
    unittest.main()
