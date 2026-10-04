"""Existing downloads and saved settings survive failures, cancellation and other windows."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from torrent_finder import bookmarks, libgen, madokami, settings_backup, state, stats, store
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.search_profiles import ProfileLibrary
from torrent_finder.ui import history as history_ui, storage as storage_ui
from isolation import isolate_store, restart_store

ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    """A streamed HTTP response; an exception among *chunks* is raised mid-transfer."""

    def __init__(self, chunks, headers=None):
        self.status_code = 200
        self.headers = headers or {}
        self.chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, chunk_size):
        for chunk in self.chunks:
            if isinstance(chunk, BaseException):
                raise chunk
            yield chunk


class DirectDownloadTests(unittest.TestCase):
    """A01: a re-download never truncates, deletes or replaces the existing file."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.existing = self.root / "Volume 01.cbz"
        self.existing.write_bytes(b"complete old volume")

    def download(self, backend, response, cancel=None):
        progress = (lambda done, total: done and cancel.set()) if cancel else None
        if backend == "madokami":
            session = Mock()
            session.get = response if callable(response) and not isinstance(response, FakeResponse) else Mock(return_value=response)
            with patch.object(madokami, "_get_session", return_value=session):
                return madokami.download_file("/Manga/V/Volume%2001.cbz", str(self.root),
                                              cancel_event=cancel, progress_cb=progress)
        get = response if callable(response) and not isinstance(response, FakeResponse) else Mock(return_value=response)
        with patch.object(libgen.requests, "get", get):
            return libgen.download_file("https://cdn.test/get", str(self.root), "Volume 01.cbz",
                                        cancel_event=cancel, progress_cb=progress)

    def files(self):
        return sorted(p.name for p in self.root.iterdir())

    def test_interruptions_keep_the_previous_file_and_leave_no_partial_output(self):
        failures = {
            "cancel": lambda: FakeResponse([b"new", b"more"]),
            "network": lambda: FakeResponse([b"new", requests.ConnectionError("reset")]),
            "disk": lambda: FakeResponse([b"new", OSError("disk full")]),
            "before bytes": lambda: Mock(side_effect=requests.ConnectionError("refused")),
        }
        for backend in ("madokami", "libgen"):
            for name, response in failures.items():
                with self.subTest(backend=backend, failure=name):
                    cancel = threading.Event() if name == "cancel" else None
                    self.assertIsNone(self.download(backend, response(), cancel))
                    self.assertEqual(self.existing.read_bytes(), b"complete old volume")
                    self.assertEqual(self.files(), ["Volume 01.cbz"])

    def test_ctrl_c_removes_partial_bytes_and_propagates(self):
        for backend in ("madokami", "libgen"):
            with self.subTest(backend=backend), self.assertRaises(KeyboardInterrupt):
                self.download(backend, FakeResponse([b"new", KeyboardInterrupt()]))
            self.assertEqual(self.existing.read_bytes(), b"complete old volume")
            self.assertEqual(self.files(), ["Volume 01.cbz"])

    def test_completed_download_with_a_taken_name_is_numbered(self):
        first = self.download("madokami", FakeResponse([b"new ", b"volume"], {"Content-Length": "10"}))
        second = self.download("libgen", FakeResponse([b"another"]))
        self.assertEqual(Path(first).name, "Volume 01 (1).cbz")
        self.assertEqual(Path(second).name, "Volume 01 (2).cbz")
        self.assertEqual(Path(first).read_bytes(), b"new volume")
        self.assertEqual(self.existing.read_bytes(), b"complete old volume")
        self.assertEqual(self.files(), ["Volume 01 (1).cbz", "Volume 01 (2).cbz", "Volume 01.cbz"])

    def test_interrupted_new_download_never_appears_under_its_final_name(self):
        self.existing.unlink()
        self.assertIsNone(self.download("libgen", FakeResponse([b"partial", requests.ConnectionError()])))
        self.assertEqual(self.files(), [])
        saved = self.download("libgen", FakeResponse([b"whole"]))
        self.assertEqual(Path(saved).name, "Volume 01.cbz")
        self.assertEqual(self.files(), ["Volume 01.cbz"])


class UnreadableStateTests(unittest.TestCase):
    """A02: a failed first read never lets defaults replace the saved file."""

    def setUp(self):
        self.original = {"settings": {"download_dir": "D:/Media"}, "stats": {"session_count": 4},
                         "history": [{"query": "Saki", "provider": "anime", "timestamp": "2026-10-01"}]}
        self.path = isolate_store(self, self.original)
        self.before = self.path.read_bytes()
        delays = patch.object(store, "_RETRY_DELAYS", (0, 0))
        delays.start()
        self.addCleanup(delays.stop)

    def test_transient_read_failure_preserves_the_file_until_a_successful_retry(self):
        with patch("torrent_finder.store.open", side_effect=PermissionError(13, "in use"), create=True):
            problem = store.problem()
            self.assertIsNotNone(problem)
            self.assertFalse(problem.damaged)
            self.assertEqual(store.read(), {})
        stats.record_session_start()
        state.add_history_entry("Session search", "anime")
        with self.assertRaises(ValueError):
            state.clear_history()
        store.flush()  # e.g. app exit; the file has become readable again by now
        self.assertEqual(self.path.read_bytes(), self.before)

        self.assertTrue(store.retry_load())
        self.assertEqual(state.load_setting("download_dir"), "D:/Media")
        store.flush()
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["stats"]["session_count"], 5)
        self.assertEqual([e["query"] for e in saved["history"]], ["Session search", "Saki"])

    def test_damaged_file_is_kept_aside_before_starting_fresh(self):
        self.path.write_text("{broken", encoding="utf-8")
        self.assertTrue(store.problem().damaged)
        with self.assertRaises(ValueError):
            bookmarks.save_search(AnimeProvider(), "Saki")
        with self.assertRaises(ValueError):
            settings_backup.export_settings(self.path.parent / "export.json")
        aside = store.set_aside_unreadable()
        self.assertEqual(Path(aside).read_text(encoding="utf-8"), "{broken")
        self.assertIsNone(store.problem())
        bookmarks.save_search(AnimeProvider(), "Saki")
        self.assertEqual([e["name"] for e in bookmarks.entries()], ["Saki"])

    def test_new_install_still_initializes_settings(self):
        self.path.unlink()
        restart_store()
        self.assertIsNone(store.problem())
        stats.record_session_start()
        store.flush()
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["stats"]["session_count"], 1)

    def test_startup_screen_offers_recovery_without_writing(self):
        self.path.write_text("{broken", encoding="utf-8")
        choices = iter(["retry", "continue"])

        def choose(items, **kwargs):
            self.assertIn("Nothing is saved until this is resolved", kwargs["footer"])
            value = next(choices)
            return next(i for i, item in enumerate(items) if item.value == value)
        with patch.object(storage_ui, "arrow_select", side_effect=choose):
            storage_ui.storage_problem_prompt()
        self.assertIsNotNone(store.problem())
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{broken")

        with patch.object(storage_ui, "arrow_select", side_effect=lambda items, **kw: [i.value for i in items].index("aside")), \
             patch.object(storage_ui, "console"), patch.object(storage_ui.readchar, "readkey"):
            storage_ui.storage_problem_prompt()
        self.assertIsNone(store.problem())
        self.assertEqual([p.read_text(encoding="utf-8") for p in self.path.parent.glob("*.unreadable-*")], ["{broken"])

    def test_startup_shows_recovery_before_loading_provider_settings(self):
        from torrent_finder import main
        self.path.write_text("{broken", encoding="utf-8")
        calls = []
        with patch.object(storage_ui, "storage_problem_prompt", side_effect=lambda: calls.append("prompt")), \
             patch.object(main, "load_state", side_effect=lambda providers: calls.append("load")), \
             patch.object(main, "advise_limited_terminal"), \
             patch.object(main, "show_security_warning", return_value=False), patch.object(main, "console"):
            main._main_loop(main._build_parser().parse_args([]))
        self.assertEqual(calls, ["prompt", "load"])


class ConcurrentWindowTests(unittest.TestCase):
    """A04: a stale window saves only its own changes, never its old copy of the file."""

    def setUp(self):
        self.path = isolate_store(self, {"stats": {"session_count": 5}})

    def other_window_writes(self, change):
        data = json.loads(self.path.read_text(encoding="utf-8"))
        change(data)
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def test_exit_save_keeps_newer_bookmarks_deletions_and_counters(self):
        bookmarks.save_search(AnimeProvider(), "Old")
        stats.record_session_start()  # this window: one session
        self.other_window_writes(lambda d: (d.__setitem__("bookmarks", []), d["stats"].__setitem__("session_count", 9)))
        store.flush()
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["bookmarks"], [])  # the other window's deletion stays deleted
        self.assertEqual(saved["stats"]["session_count"], 10)

    def test_reads_and_explicit_saves_build_on_the_other_windows_changes(self):
        stale_library = ProfileLibrary.load()
        self.other_window_writes(lambda d: d.setdefault("settings", {}).__setitem__("download_dir", "E:/Other"))
        self.assertEqual(state.load_setting("download_dir"), "E:/Other")
        stale_library.create("Laptop", {"selected": ["anime"]})
        stale_library.save()
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["settings"]["download_dir"], "E:/Other")
        self.assertEqual(ProfileLibrary.load().current["name"], "Laptop")

    def test_import_applies_to_the_settings_saved_when_confirmed(self):
        data = {"settings": {"hide_stream_output": True}}
        _, preview = settings_backup.prepare_import(data, "replace")
        self.assertTrue(preview)
        self.other_window_writes(lambda d: d.__setitem__("bookmarks", [{"marker": "kept"}]))
        store.commit(settings_backup.import_change(data, "replace"))
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["bookmarks"], [{"marker": "kept"}])
        self.assertTrue(saved["settings"]["hide_stream_output"])

    def test_second_interpreter_bookmark_survives_this_windows_exit(self):
        stats.record_session_start()
        home = str(self.path.parent)
        env = dict(os.environ, USERPROFILE=home, HOME=home, LOCALAPPDATA=home, APPDATA=home)
        code = ("import sys; sys.path.insert(0, sys.argv[1])\n"
                "from torrent_finder import store\n"
                "store.STATE_PATH, store.LEGACY_STATE_PATHS = sys.argv[2], []\n"
                "from torrent_finder import bookmarks\n"
                "from torrent_finder.providers.anime_provider import AnimeProvider\n"
                "bookmarks.save_search(AnimeProvider(), 'Other window')\n")
        subprocess.run([sys.executable, "-c", code, str(ROOT), str(self.path)],
                       env=env, check=True, capture_output=True, timeout=120)
        self.assertEqual([e["name"] for e in bookmarks.entries()], ["Other window"])
        store.flush()
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual([e["name"] for e in saved["bookmarks"]], ["Other window"])
        self.assertEqual(saved["stats"]["session_count"], 6)

    def test_save_waits_for_another_window_then_reports_without_changes(self):
        state.add_history_entry("Pending", "anime")
        before = self.path.read_bytes()
        with patch.object(store, "LOCK_TIMEOUT", 0.1), store._file_lock(store.STATE_PATH, 1):
            with self.assertRaises(store.SaveError) as caught:
                state.clear_history()
        self.assertIn("Another Torrent Finder window", str(caught.exception))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual([e["query"] for e in state.load_history()], ["Pending"])
        state.clear_history()
        self.assertEqual(state.load_history(), [])


class ExplicitSaveFailureTests(unittest.TestCase):
    """A05: a failed Save/Clear/Reset says so, keeps saved data, and can be retried."""

    def setUp(self):
        self.path = isolate_store(self)
        state.add_history_entry("Saki", "anime")
        stats.record_session_start()
        store.flush()
        self.before = self.path.read_bytes()

    def failing_disk(self):
        return patch.object(store.os, "replace", side_effect=PermissionError(13, "read-only"))

    def test_failures_raise_keep_data_and_retry_succeeds(self):
        library = ProfileLibrary.load()
        library.create("Laptop", {"selected": ["anime"]})
        actions = {"profile save": library.save, "clear history": state.clear_history, "reset stats": stats.reset_stats}
        for name, action in actions.items():
            with self.subTest(action=name):
                with patch.object(store, "_RETRY_DELAYS", (0,)), self.failing_disk(), \
                     self.assertRaises(store.SaveError) as caught:
                    action()
                self.assertIn("Nothing was changed", str(caught.exception))
                self.assertEqual(self.path.read_bytes(), self.before)
                self.assertEqual(ProfileLibrary.load().current["name"], "Default")
                self.assertEqual(len(state.load_history()), 1)
                self.assertEqual(stats.get_all_stats()["session_count"], 1)
        library.save()  # the same draft, once the disk is writable again
        self.assertEqual(ProfileLibrary.load().current["name"], "Laptop")
        state.clear_history()
        stats.reset_stats()
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual((saved["history"], "stats" in saved), ([], False))

    def test_history_screen_reports_a_failed_clear_and_keeps_entries(self):
        footers = []

        def select(items, on_action, footer, **kwargs):
            on_action(next(i for i, item in enumerate(items) if item.value == "clear"), items)
            footers.append(footer())
            self.assertTrue(any(isinstance(item.value, dict) for item in items))
            return None
        with patch.object(history_ui, "arrow_select", side_effect=select), \
             patch.object(history_ui, "confirm_prompt", return_value=True), \
             patch.object(history_ui, "clear_history", side_effect=store.SaveError("Couldn't save settings")):
            history_ui.history_select_prompt()
        self.assertIn("History was not cleared", footers[0])
        self.assertEqual(self.path.read_bytes(), self.before)


if __name__ == "__main__":
    unittest.main()
