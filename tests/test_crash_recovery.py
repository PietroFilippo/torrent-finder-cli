"""Edge cases that used to end the whole app with a traceback stay inside their screen."""

import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import readchar
from rich.console import Console

from torrent_finder import acquisition, bookmarks, downloader, jimaku, main, settings_backup, state
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.torrent_session import TorrentSession
from torrent_finder.ui import bookmarks as bookmarks_ui, history as history_ui, prompts, selector, table
from isolation import isolate_store

K = readchar.key


def quiet_console():
    return Console(file=io.StringIO(), width=72, height=20, color_system=None)


class ExpandedDetailsTests(unittest.TestCase):
    """A11: details expanded, then the view refined to zero rows."""

    def select(self, refinements, keys):
        with patch.object(table, "console", quiet_console()), \
             patch.object(table, "refine_results", side_effect=refinements), \
             patch.object(table.readchar, "readkey", side_effect=keys):
            return table.interactive_select([{"name": "Other"}, {"name": "Example"}])

    def test_detail_keys_after_filtering_to_nothing_are_safe(self):
        keys = ["i", "f", "[", "]", "i", K.ENTER, K.DOWN, K.ESC]
        self.assertIsNone(self.select([("Saki", "title", "name")], keys))

    def test_clearing_the_filter_restores_navigation(self):
        keys = ["i", "f", "]", "f", K.DOWN, "[", K.ENTER]
        result = self.select([("Saki", "title", "name"), ("", "contains", "relevance")], keys)
        self.assertEqual(result, ("one", 1))


class ClearHistoryNavigationTests(unittest.TestCase):
    """A12: the selector keeps a valid cursor when an action shrinks its list."""

    def run_history(self, entries, keys):
        isolate_store(self)
        for number in range(entries):
            state.add_history_entry(f"Search {number}", "anime")
        with patch.object(selector, "console", quiet_console()), \
             patch.object(selector.sys, "stdout", io.StringIO()), \
             patch.object(selector.readchar, "readkey", side_effect=keys), \
             patch.object(history_ui, "confirm_prompt", return_value=True), \
             patch.object(history_ui, "console", quiet_console()):
            return history_ui.history_select_prompt()

    def test_every_key_works_after_clearing(self):
        for entries in (1, 2, 5):
            for after in ([K.ENTER], [K.HOME, K.PAGE_DOWN, K.PAGE_UP, K.END, K.UP, K.DOWN, K.ENTER]):
                with self.subTest(entries=entries, after=after):
                    # END → Back, UP → Clear history, ENTER clears and stays.
                    self.assertIsNone(self.run_history(entries, [K.END, K.UP, K.ENTER, *after]))
                    self.assertEqual(state.load_history(), [])

    def test_start_index_beyond_the_list_selects_its_last_enabled_row(self):
        items = [selector.SelectItem("Only", 1), selector.SelectItem("Hidden", 2, enabled=False)]
        self.assertEqual(selector._valid_cursor(items, 7), 0)
        self.assertEqual(selector._valid_cursor(items, 1), 0)


class MarkupNameTests(unittest.TestCase):
    """A19: names from bookmarks and sources render literally."""

    NAMES = ("Example [/not-a-style]", "[SubsPlease] Show - 01 [1080p]", "Plain [bold]name[/bold]")

    def test_bookmark_actions_open_for_names_that_look_like_markup(self):
        isolate_store(self)
        for name in self.NAMES:
            bookmarks.save_search(AnimeProvider(), name)
        rendered = []

        def capture(items, title, **kwargs):
            if title.startswith("Bookmarks"):
                return None if len(rendered) == len(self.NAMES) else len(rendered)
            screen = quiet_console()
            screen.print(selector._build_panel(items, 0, title, False))
            rendered.append(screen.file.getvalue())
            return None
        with patch.object(bookmarks_ui, "arrow_select", side_effect=capture):
            self.assertIsNone(bookmarks_ui.bookmark_menu())
        for name, frame in zip(self.NAMES, rendered):
            self.assertIn(name, frame)
        self.assertEqual([e["name"] for e in bookmarks.entries()], list(self.NAMES))

    def test_download_panels_show_source_names_literally(self):
        for name in self.NAMES:
            with self.subTest(name=name):
                screen = Console(file=io.StringIO(), width=120, color_system=None)
                with patch.object(acquisition, "console", screen), \
                     patch.object(acquisition.readchar, "readkey"), \
                     patch("torrent_finder.libgen.resolve_download_url", return_value=None):
                    outcome = acquisition.LibgenAcquisition().pick(
                        {"name": name, "lg_md5": "abc", "page_url": "https://example.test/[/x]"})
                self.assertEqual(outcome.action, "back")
                self.assertIn(name, screen.file.getvalue())
                self.assertIn("https://example.test/[/x]", screen.file.getvalue())


class DownloadFolderTests(unittest.TestCase):
    """A10: an unusable download folder is explained and can be replaced in place."""

    MAGNET = "magnet:?xt=urn:btih:" + "a" * 40

    def setUp(self):
        isolate_store(self)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        blocker = Path(directory.name) / "not-a-folder"
        blocker.write_text("a file where a folder should be", encoding="utf-8")
        self.broken = str(blocker / "Downloads")  # like a disconnected drive: can't be created
        self.working = str(Path(directory.name) / "Downloads")
        state.save_setting("download_dir", self.broken)

    def choose(self, *values):
        values = iter(values)
        return lambda items, **kwargs: [item.value for item in items].index(next(values))

    def use_working_folder(self):
        state.save_setting("download_dir", self.working)

    def test_cli_downloads_explain_and_start_nothing(self):
        screen = Console(file=io.StringIO(), width=300, color_system=None)
        calls = {
            "aria2": lambda: downloader.download_with_aria2(self.MAGNET, [1]),
            "aria2 batch": lambda: downloader.download_many_with_aria2([self.MAGNET]),
            "webtorrent": lambda: downloader.download_with_webtorrent(self.MAGNET),
            "peerflix": lambda: downloader.download_with_peerflix(self.MAGNET),
        }
        with patch.object(downloader.shutil, "which", return_value="tool"), \
             patch.object(downloader, "_spawn_detached") as spawn, patch.object(downloader, "console", screen):
            for name, call in calls.items():
                with self.subTest(name=name):
                    self.assertFalse(call())
        spawn.assert_not_called()
        self.assertEqual(screen.file.getvalue().count(f"Can't save to {self.broken}"), len(calls))

    def test_choosing_another_folder_makes_it_ready_and_back_declines(self):
        with patch.object(prompts, "arrow_select", side_effect=self.choose("choose")), \
             patch.object(prompts, "download_dir_prompt", side_effect=self.use_working_folder):
            self.assertTrue(prompts.download_dir_ready())
        self.assertTrue(os.path.isdir(self.working))
        state.save_setting("download_dir", self.broken)
        with patch.object(prompts, "arrow_select", return_value=None):
            self.assertFalse(prompts.download_dir_ready())

    def test_method_menu_retries_the_same_selection_after_choosing_a_folder(self):
        result = {"name": "Example", "source": "Nyaa", "info_hash": "a" * 40}
        session = TorrentSession(result, self.MAGNET)
        session.set_selected_files([1, 3])
        adapter = Mock(style="magnet-direct")
        adapter.pick.return_value = acquisition.PickOutcome("menu", self.MAGNET)
        provider = SimpleNamespace(slug="anime", result_sort="relevance", filter_summary=lambda: "No filters")
        quiet = [patch.object(main, name) for name in ("clear_screen", "record_torrent_picked",
                                                       "record_method_pick", "record_method_complete")]
        for patcher in quiet:
            patcher.start()
            self.addCleanup(patcher.stop)
        with patch.object(main, "console", quiet_console()), \
             patch("torrent_finder.qbittorrent.configured", return_value=False), \
             patch.object(main.acquisition, "for_result", return_value=adapter), \
             patch.object(main, "TorrentSession", return_value=session), \
             patch.object(main, "interactive_select", return_value=("one", 0)), \
             patch.object(main, "download_method_prompt", side_effect=["aria", "aria"]) as methods, \
             patch.object(main, "download_complete_prompt", return_value="next"), \
             patch.object(main, "download_with_aria2", return_value=True) as aria, \
             patch.object(prompts, "arrow_select", side_effect=self.choose("back", "choose")), \
             patch.object(prompts, "download_dir_prompt", side_effect=self.use_working_folder):
            self.assertEqual(main.browse_results(provider, [result]), "next")
        self.assertEqual(methods.call_count, 2)  # Back returned to the same download options
        aria.assert_called_once_with(self.MAGNET, session.download_indexes)
        self.assertEqual(session.selected_files, [1, 3])

    def test_direct_downloads_check_the_folder_before_any_request(self):
        with patch.object(prompts, "arrow_select", return_value=None), \
             patch("torrent_finder.libgen.resolve_download_url") as resolve:
            outcome = acquisition.LibgenAcquisition().pick({"name": "Book", "lg_md5": "abc"})
        self.assertEqual(outcome.action, "back")
        resolve.assert_not_called()
        with patch.object(jimaku, "console", quiet_console()), patch.object(jimaku.requests, "get") as get:
            self.assertIsNone(jimaku._download("https://example.test/sub.srt", "sub.srt", "key"))
        get.assert_not_called()


class HistoryTimestampTests(unittest.TestCase):
    """A14: import accepts only timezone-aware timestamps; History tolerates any row."""

    def test_import_rejects_timestamps_without_a_timezone(self):
        def payload(timestamp):
            return {"history": [{"query": "Saki", "provider": "anime", "timestamp": timestamp}]}
        settings_backup.validate_payload(payload("2026-10-03T12:00:00+00:00"))
        for timestamp in ("2026-10-03T12:00:00", "2026-10-03", "yesterday", ""):
            with self.subTest(timestamp=timestamp), self.assertRaisesRegex(ValueError, "with a timezone"):
                settings_backup.validate_payload(payload(timestamp))

    def test_history_screen_helpers_accept_mixed_rows(self):
        recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        rows = [{"query": "aware", "timestamp": recent}, {"query": "naive", "timestamp": "2026-10-03T12:00:00"},
                {"query": "malformed", "timestamp": "soon"}, {"query": "absent"}, {"query": "number", "timestamp": 5}]
        self.assertEqual(history_ui._sort_entries(rows, "Newest first")[0]["query"], "aware")
        self.assertEqual(history_ui._sort_entries(rows, "Oldest first")[-1]["query"], "aware")
        for date_range in ("Today", "This week", "This month"):
            self.assertEqual([e["query"] for e in history_ui._filter_by_date(rows, date_range)], ["aware"])
        self.assertEqual(history_ui._relative_time(recent), "2h ago")
        self.assertEqual(history_ui._relative_time("2026-10-03T12:00:00"), "")


if __name__ == "__main__":
    unittest.main()
