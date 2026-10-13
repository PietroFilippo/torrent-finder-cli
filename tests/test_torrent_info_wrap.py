"""Torrent info wraps source paragraphs and file names in the current viewport."""

import io
import textwrap
import unittest
from unittest.mock import patch

import isolation  # noqa: F401
import readchar
from rich.cells import cell_len
from rich.console import Console

from torrent_finder.torrent_info import TorrentInfo
from torrent_finder.ui import prompts, selector


class TorrentInfoWrapTests(unittest.TestCase):
    def capture_rows(self, info, widths):
        screen = Console(file=io.StringIO(), width=widths[0], height=36)
        drawn = []

        def select(items, **kwargs):
            for width in widths:
                screen.width = width
                if "refresh" in kwargs:
                    kwargs["refresh"]()
                drawn.append([item.label for item in items])

        with patch.object(prompts, "console", screen), \
             patch("torrent_finder.torrent_info.fetch_torrent_info", return_value=(info, "")), \
             patch.object(prompts, "arrow_select", side_effect=select):
            prompts.torrent_info_screen({"source": "Nyaa"})
        return drawn

    def section(self, rows, label):
        start = rows.index(label) + 1
        end = next((i for i in range(start, len(rows)) if not rows[i] or rows[i] == "Back"), len(rows))
        return rows[start:end]

    def test_japanese_chinese_and_emoji_fit_in_terminal_cells(self):
        paragraph = "日本語の説明 中文字幕 😀 " * 30
        info = TorrentInfo(source="Nyaa", title="Anime", description=paragraph)
        for width in (40, 80, 137):
            with self.subTest(width=width):
                rows = self.section(self.capture_rows(info, [width])[0], "Description")
                self.assertTrue(rows)
                for row in rows:
                    self.assertLessEqual(cell_len(row), width - 8)
                self.assertEqual("".join(row.strip() for row in rows).replace(" ", ""),
                                 paragraph.replace(" ", ""))

    def test_resize_rewraps_description_and_files_from_original_text(self):
        paragraph = "日本語の説明と字幕 😀 " * 20
        filename = "日本語の長いファイル名😀" * 16 + ".mkv"
        info = TorrentInfo(source="Nyaa", title="Anime", description=paragraph,
                           files=[(filename, "1 GB")])
        frames = self.capture_rows(info, [80, 50, 80])
        self.assertNotEqual(frames[0], frames[1])
        self.assertEqual(frames[0], frames[2])
        for width, rows in zip((80, 50, 80), frames):
            for label in ("Description", "Files (1)"):
                for row in self.section(rows, label):
                    self.assertLessEqual(cell_len(row), width - 8)
        self.assertEqual("".join(row.strip() for row in self.section(frames[1], "Files (1)")),
                         filename + "  (1 GB)")

    def test_long_unbroken_urls_and_file_names_are_not_lost(self):
        for token in ("https://example.org/" + "日本語😀" * 40,
                      "https://example.org/" + "long-file-name_" * 40):
            with self.subTest(token=token[:30]):
                info = TorrentInfo(source="Nyaa", title="Anime", description=token,
                                   files=[(token, "")])
                rows = self.capture_rows(info, [40])[0]
                for label in ("Description", "Files (1)"):
                    wrapped = self.section(rows, label)
                    self.assertEqual("".join(row.strip() for row in wrapped), token)
                    self.assertTrue(all(cell_len(row) <= 32 for row in wrapped))

    def test_ascii_description_keeps_legacy_breaks_and_blank_paragraphs(self):
        description = ("A familiar ASCII description with hyphenated-words, a\ttab and  double spaces. " * 4
                       + "\n\nhttps://example.org/" + "release-name_" * 20)
        info = TorrentInfo(source="Nyaa", title="Anime", description=description,
                           files=[("episode.mkv", "1 GB")])
        for width in (40, 80, 137):
            with self.subTest(width=width):
                rows = self.capture_rows(info, [width])[0]
                expected = ["  " + line for paragraph in description.splitlines()
                            for line in (textwrap.wrap(paragraph, max(8, width - 12)) or [""])]
                start = rows.index("Description") + 1
                self.assertEqual(rows[start:start + len(expected)], expected)
                self.assertIn("    episode.mkv  (1 GB)", rows)

    def test_real_selector_rewraps_before_drawing_resized_frame(self):
        screen = Console(file=io.StringIO(), width=80, height=36)
        info = TorrentInfo(source="Nyaa", title="Anime", description="日本語😀 " * 30)
        drawn = []
        original_panel = selector._build_panel

        def build(items, *args, **kwargs):
            drawn.append((screen.width, [item.label for item in items]))
            return original_panel(items, *args, **kwargs)

        def keys():
            screen.width = 50
            yield readchar.key.HOME
            yield readchar.key.ESC

        keypresses = keys()
        with patch.object(prompts, "console", screen), \
             patch.object(selector, "console", screen), \
             patch("torrent_finder.torrent_info.fetch_torrent_info", return_value=(info, "")), \
             patch.object(selector, "_build_panel", side_effect=build), \
             patch.object(selector, "_render", return_value=True), \
             patch.object(selector.threading, "Thread"), \
             patch.object(selector.readchar, "readkey", side_effect=lambda: next(keypresses)), \
             patch.object(selector.sys, "stdout", io.StringIO()):
            prompts.torrent_info_screen({"source": "Nyaa"})
        self.assertEqual([width for width, _rows in drawn], [80, 50])
        self.assertNotEqual(drawn[0][1], drawn[1][1])
        for width, rows in drawn:
            self.assertTrue(all(cell_len(row) <= width - 8
                                for row in self.section(rows, "Description")))

    def test_discarded_frame_retry_rewraps_at_new_width(self):
        screen = Console(file=io.StringIO(), width=80, height=36)
        info = TorrentInfo(source="Nyaa", title="Anime", description="日本語😀 " * 30)
        drawn = []
        original_panel = selector._build_panel

        def build(items, *args, **kwargs):
            drawn.append((screen.width, [item.label for item in items]))
            return original_panel(items, *args, **kwargs)

        def render(*args, **kwargs):
            if len(drawn) == 1:
                screen.width = 50
                return False
            return True

        with patch.object(prompts, "console", screen), \
             patch.object(selector, "console", screen), \
             patch("torrent_finder.torrent_info.fetch_torrent_info", return_value=(info, "")), \
             patch.object(selector, "_build_panel", side_effect=build), \
             patch.object(selector, "_render", side_effect=render), \
             patch.object(selector.threading, "Thread"), \
             patch.object(selector.readchar, "readkey", return_value=readchar.key.ESC), \
             patch.object(selector.sys, "stdout", io.StringIO()):
            prompts.torrent_info_screen({"source": "Nyaa"})
        self.assertEqual([width for width, _rows in drawn], [80, 50])
        self.assertTrue(all(cell_len(row) <= 42
                            for row in self.section(drawn[-1][1], "Description")))

    def test_enter_on_back_after_widening_removes_rows(self):
        screen = Console(file=io.StringIO(), width=40, height=36)
        info = TorrentInfo(source="Nyaa", title="Anime", description="日本語😀 " * 30)
        live_items = []

        def capture(items, **kwargs):
            live_items.append(items)
            return selector.arrow_select(items, **kwargs)

        def keys():
            yield readchar.key.END
            screen.width = 137
            self.assertTrue(prompts_refresh[0]())
            yield readchar.key.ENTER

        prompts_refresh = []

        def select(items, **kwargs):
            prompts_refresh.append(kwargs["refresh"])
            return capture(items, **kwargs)

        keypresses = keys()
        with patch.object(prompts, "console", screen), \
             patch.object(selector, "console", screen), \
             patch("torrent_finder.torrent_info.fetch_torrent_info", return_value=(info, "")), \
             patch.object(prompts, "arrow_select", side_effect=select), \
             patch.object(selector, "_render", return_value=True), \
             patch.object(selector.threading, "Thread"), \
             patch.object(selector.readchar, "readkey", side_effect=lambda: next(keypresses)), \
             patch.object(selector.sys, "stdout", io.StringIO()):
            prompts.torrent_info_screen({"source": "Nyaa"})
        self.assertEqual(live_items[0][-1].value, "back")


if __name__ == "__main__":
    unittest.main()
