"""Session extraction boundaries: shared updates and search navigation outcomes."""

from contextlib import ExitStack
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch

import isolation  # noqa: F401  # keep startup and search persistence isolated
from torrent_finder import main, state
from torrent_finder.search_errors import SearchError
from torrent_finder.ui import chrome as frames


class SessionUpdateTests(unittest.TestCase):
    def setUp(self):
        self.check = SimpleNamespace(done=threading.Event(), info=None)
        self.session = main._Session(None, None, None, None, None, self.check,
                                     update_msg="startup notice")

    def test_idle_poll_loads_late_update_once_and_looks_up_module_dependencies(self):
        poll = self.session.poll_update
        self.assertEqual(poll(), (None, "startup notice"))
        info = {"kind": "git", "behind": 2}
        self.check.info = info
        self.check.done.set()
        with patch.object(main, "notice_line", return_value="update notice") as notice, \
             patch.object(main, "status_label", return_value="new version") as label, \
             patch.object(frames, "announce") as announce:
            self.assertEqual(poll(), (info, "update notice\nstartup notice"))
            self.assertEqual(poll(), (info, "update notice\nstartup notice"))
        notice.assert_called_once_with(info)
        label.assert_called_once_with(info)
        announce.assert_called_once()

    def test_shared_update_callback_keeps_refused_offer_and_consumes_applied_offer(self):
        callback = self.session.run_pending_update
        info = {"kind": "git", "behind": 2}
        self.session.update_info = info
        self.session.update_loaded = True
        with patch.object(main, "_run_update_flow", side_effect=[False, True]) as update:
            callback()
            self.assertIs(self.session.update_info, info)
            self.assertEqual(self.session.update_msg, "startup notice")
            callback()
        self.assertEqual(update.call_count, 2)
        update.assert_called_with(info)
        self.assertEqual(self.session.poll_update(), (None, ""))


def inline_worker(*, target, daemon):
    """Complete the worker deterministically, without leaving a test thread behind."""
    return SimpleNamespace(start=target)


class SearchNavigationTests(unittest.TestCase):
    def setUp(self):
        self.provider = SimpleNamespace(name="Fixture", slug="fixture", active_presets=[],
                                        last_queries=["previous"], _history_notice="older filters")
        self.stopped = threading.Event()
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(main.threading, "Thread", side_effect=inline_worker))
        self.listener = stack.enter_context(patch.object(main, "start_esc_listener", return_value=self.stopped))
        stack.enter_context(patch.object(main, "ProgressScreen"))
        self.record = stack.enter_context(patch.object(main, "record_search"))
        self.history = stack.enter_context(patch.object(state, "add_history_entry"))
        self.browse = stack.enter_context(patch.object(main, "browse_results", return_value="back"))
        self.search = stack.enter_context(patch("torrent_finder.search_session.search_many", return_value=[]))

    def test_cancel_returns_history_notice_stops_listener_and_records_nothing(self):
        self.search.return_value = [{"name": "one"}]
        def cancel(cancel_event, **kwargs):
            cancel_event.set()
            self.assertIsInstance(kwargs["finish_event"], threading.Event)
            return self.stopped
        self.listener.side_effect = cancel
        outcome, notice = main._search_and_browse(self.provider, ["one"], None)
        self.assertEqual(outcome, "back")
        self.assertIn("Search cancelled", notice)
        self.assertIn("older filters", notice)
        self.assertEqual(self.provider.last_queries, ["previous"])
        self.assertTrue(self.stopped.is_set())
        self.history.assert_not_called()
        self.record.assert_not_called()
        self.browse.assert_not_called()

    def test_empty_or_failed_search_returns_notice_without_history_or_results(self):
        for error, expected in ((None, "No results found."),
                                (SearchError("Fixture [offline]"), "Fixture \\[offline]"),
                                (RuntimeError("internal detail"), "Search could not be completed.")):
            with self.subTest(error=error):
                self.search.side_effect = error
                outcome, notice = main._search_and_browse(self.provider, ["one"], None)
                self.assertEqual(outcome, "back")
                self.assertIn(expected, notice)
                self.assertIn("older filters", notice)
                self.assertEqual(self.provider.last_queries, ["one"])
                self.assertTrue(self.stopped.is_set())
        self.history.assert_not_called()
        self.record.assert_not_called()
        self.browse.assert_not_called()

    def test_multi_title_success_records_each_title_and_carries_missing_and_engine_notes(self):
        class Rows(list):
            notices = ("Fixture timed out",)
        rows = Rows([{"name": "one", "matched_queries": ["one"]}])
        self.search.return_value = rows
        queries = ["one", "two"]
        outcome, notice = main._search_and_browse(self.provider, queries, None)
        self.assertEqual((outcome, notice), ("back", None))
        self.assertEqual(self.provider.last_queries, queries)
        self.assertEqual([call.args[0] for call in self.history.call_args_list], queries)
        self.assertEqual([call.args[1] for call in self.record.call_args_list], queries)
        self.assertIs(self.browse.call_args.args[1], rows)
        self.assertIn("No torrents for 1 of 2 titles: two", self.browse.call_args.kwargs["note"])
        self.assertIn("Fixture timed out", self.browse.call_args.kwargs["note"])

    def test_empty_live_session_still_browses_and_completed_download_goes_next(self):
        class Rows(list):
            session = object()
            notices = ("Fixture is not logged in",)
        rows = Rows()
        self.search.return_value = rows
        self.browse.return_value = "next"
        self.assertEqual(main._search_and_browse(self.provider, ["one"], None), ("next", None))
        self.browse.assert_called_once_with(self.provider, rows, note="Fixture is not logged in")
        self.history.assert_called_once_with("one", "fixture", [])


if __name__ == "__main__":
    unittest.main()
