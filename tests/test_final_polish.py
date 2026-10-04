"""Honest client handoff, compact screens that fit, and subtitles only for streamed episodes."""

import io
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rich.console import Console

from torrent_finder import acquisition, bookmarks, downloader, main, state
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.torrent_meta import TorrentFile, TorrentMetadata
from torrent_finder.ui import bookmarks as bookmarks_ui, prompts, selector, table, theme
from isolation import isolate_store

MAGNET = "magnet:?xt=urn:btih:" + "a" * 40


class ClientHandoffTests(unittest.TestCase):
    """A06: a magnet the system can't open is reported, not counted as sent."""

    def test_failed_handoff_keeps_the_download_options(self):
        isolate_store(self)
        provider = SimpleNamespace(slug="anime", result_sort="relevance", filter_summary=lambda: "No filters")
        result = {"name": "Example", "source": "Nyaa", "info_hash": "a" * 40}
        adapter = Mock()
        adapter.pick.return_value = acquisition.PickOutcome("menu", MAGNET)
        screen = Console(file=io.StringIO(), width=200)
        refused = OSError(1155, "No application is associated with the specified file for this operation")
        with patch.object(main.acquisition, "for_result", return_value=adapter), \
             patch.object(main, "interactive_select", side_effect=[("one", 0), None]), \
             patch.object(main, "download_method_prompt", side_effect=["t", "back"]) as menu, \
             patch.object(main, "open_magnet", side_effect=refused), \
             patch.object(main, "record_magnet_dispatch") as dispatched, \
             patch.object(main, "download_complete_prompt") as finished, \
             patch.object(main, "console", screen), patch.object(main.readchar, "readkey"), \
             patch.object(main, "clear_screen"), patch.object(main, "record_torrent_picked"), \
             patch.object(main, "record_method_pick"), \
             patch("torrent_finder.qbittorrent.configured", return_value=False):
            self.assertEqual(main.browse_results(provider, [result]), "back")
        self.assertEqual(menu.call_count, 2)
        dispatched.assert_not_called()
        finished.assert_not_called()
        printed = screen.file.getvalue()
        self.assertEqual(printed.count("Couldn't open the magnet link"), 1)
        self.assertIn("No application is associated", printed)
        self.assertNotIn("handed to", printed)

    def test_failed_batch_handoff_is_not_ok(self):
        with patch("torrent_finder.downloader.open_magnet", side_effect=OSError("no handler")):
            outcome = acquisition.MagnetDirect().batch_item(
                {"name": "Example", "info_hash": "a" * 40},
                download_dir="", cancel_event=None, set_status=lambda text: None)
        self.assertFalse(outcome.ok)


class CompactScreenTests(unittest.TestCase):
    """A16 / A18 / A21: compact frames fit and describe what keys really do."""

    def caption(self, picked, width=40):
        screen = Console(file=io.StringIO(), width=width, height=16)
        with patch.object(table, "console", screen):
            layout = table._table_layout(width, False, False)
            return table._table_caption([{"name": "One"}, {"name": "Two"}], 0, layout, False, 1,
                                        frozenset(picked)).plain

    def test_compact_results_say_what_enter_does(self):
        self.assertIn("Enter open", self.caption([]))
        self.assertIn("Enter download 1", self.caption([0]))
        two = self.caption([0, 1])
        self.assertIn("Enter download 2", two)
        self.assertIn("Esc back", two)
        controls = two.splitlines()[-3:]  # below the selected row's (wrapping) metadata
        self.assertTrue(all(len(line) <= 36 for line in controls), controls)

    def test_empty_bookmarks_explain_how_to_save_one(self):
        isolate_store(self)
        footers = []
        with patch.object(bookmarks_ui, "arrow_select",
                          side_effect=lambda items, **kw: footers.append(kw["footer"])):
            bookmarks_ui.bookmark_menu()
            bookmarks.save_search(AnimeProvider(), "Saki")
            bookmarks_ui.bookmark_menu()
        self.assertIn("b saves a listing", footers[0])
        self.assertIn("Bookmark current search", footers[0])
        self.assertEqual(footers[1], "Enter review • Esc back")

    def main_menu(self):
        isolate_store(self)
        state.save_setting("download_dir", "E:\\" + "\\".join(["Very long folder"] * 8))
        captured = []
        with patch.object(prompts, "console", Console(file=io.StringIO(), width=100, height=32)), \
             patch.object(prompts, "arrow_select", side_effect=lambda items, **kw: captured.append((items, kw))):
            prompts.provider_select_prompt()
        return captured[0]

    def frame(self, items, kw, focus, width, height):
        screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
        with patch.object(selector, "console", screen), patch.object(prompts, "console", screen):
            footer = kw["footer"]()
            screen.print(selector._build_panel(items, focus, kw["title"], False, footer=footer))
        return footer, screen.file.getvalue()

    def test_resizing_the_open_main_menu_keeps_the_focused_row_on_screen(self):
        items, kw = self.main_menu()
        folder = next(i for i, item in enumerate(items) if item.value == "__download_dir__")
        large_footer, _ = self.frame(items, kw, 0, 100, 32)
        for focus in (0, folder):
            for width, height in ((100, 32), (60, 20), (40, 16), (100, 32)):
                with self.subTest(focus=focus, width=width, height=height):
                    footer, rendered = self.frame(items, kw, focus, width, height)
                    lines = rendered.splitlines()
                    self.assertLessEqual(len(lines), height)
                    self.assertIn(theme.CURSOR, rendered)
                    if height < 24:
                        self.assertNotIn("\n\n", footer)  # no tip in compact windows
                    else:
                        self.assertEqual(footer, large_footer)  # the same tip comes back


class StreamedSubtitleTests(unittest.TestCase):
    """A20: in-torrent subtitles are fetched only for the episodes being streamed."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = directory.name
        self.files = [TorrentFile(1, "Show/Show - 01.mkv", 10), TorrentFile(2, "Show/Show - 01.srt", 1),
                      TorrentFile(3, "Show/Show - 02.mkv", 10), TorrentFile(4, "Show/Show - 02.srt", 1)]
        self.requested = []

    def fake_fetch(self, magnet, files_meta, indexes):
        self.requested.append(list(indexes))
        fetched = {}
        for index in indexes:
            path = os.path.join(self.root, f"{index}.srt")
            open(path, "w").close()
            fetched[index] = path
        return fetched

    def session(self):
        from torrent_finder.torrent_session import TorrentSession
        session = TorrentSession({"name": "Show"}, MAGNET)
        session._files_meta = TorrentMetadata("Show", self.files)
        session.files_meta_status = "ok"
        return session

    def test_episode_one_then_both_fetches_only_missing_subtitles(self):
        session = self.session()
        with patch.object(downloader, "_fetch_torrent_subs", side_effect=self.fake_fetch), \
             patch.object(downloader, "console", Console(file=io.StringIO())):
            session.set_selected_files([1])
            self.assertEqual(list(session.sub_paths), [1])
            session.set_selected_files([1, 3])
            both = session.sub_paths
            again = session.sub_paths
        self.assertEqual(self.requested, [[2], [4]])  # no re-download, nothing for unstreamed episodes
        self.assertEqual(sorted(both), [1, 3])
        self.assertEqual(again, both)

    def test_a_whole_season_gets_every_episodes_subtitles_before_playback(self):
        session = self.session()
        with patch.object(downloader, "_fetch_torrent_subs", side_effect=self.fake_fetch), \
             patch.object(downloader, "console", Console(file=io.StringIO())):
            self.assertEqual(sorted(session.sub_paths), [1, 3])
        self.assertEqual(self.requested, [[2, 4]])  # one batch: n/b never waits


if __name__ == "__main__":
    unittest.main()
