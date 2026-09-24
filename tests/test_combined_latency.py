import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import requests

from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.providers.combined_provider import CombinedProvider
from torrent_finder.search_result import SearchResult
from torrent_finder.search_control import SearchControl, SearchInterrupted, search_request


def fixture_provider(slug, fetch):
    return type(slug, (BaseProvider,), {
        "slug": slug, "name": slug, "icon": "", "categories": [],
        "_init_engines": lambda self: [SearchEngine("Fixture", "", fetch)],
    })()


class CombinedLatencyTests(unittest.TestCase):
    def test_fast_provider_is_not_queued_behind_three_slow_providers(self):
        release = threading.Event()
        fast_started = threading.Event()

        def slow(_query):
            release.wait(2)
            return []

        def fast(_query):
            fast_started.set()
            return [SearchResult(name="Saki", info_hash="a" * 40, source="Nyaa")]

        providers = [fixture_provider(f"slow{i}", slow) for i in range(3)]
        providers += [fixture_provider(f"fast{i}", fast) for i in range(8)]
        combined = CombinedProvider(providers)
        combined.restore({})
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(combined.search, "Saki")
            try:
                self.assertTrue(fast_started.wait(0.3), "Fast providers were stuck behind unrelated slow searches")
            finally:
                release.set()
                future.result(timeout=2)

    def _partial_search(self, finish_early=False):
        release, finish = threading.Event(), threading.Event()
        progress = []

        def slow(_query):
            release.wait(2)
            return []

        def report(value):
            progress.append(value)
            if finish_early and value.results:
                finish.set()

        provider = fixture_provider("anime", slow)
        def engines(_self):
            return [SearchEngine("Slow", "", slow), SearchEngine("Fast", "", lambda _q: [
                SearchResult(name="Saki", info_hash="a" * 40, source="Nyaa")])]
        with patch.object(type(provider), "_init_engines", engines):
            combined = CombinedProvider([provider])
            combined.restore({})
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(combined.search_many, ["Saki"], on_progress=report,
                                         finish_event=finish, timeout=1 if finish_early else 0.15)
                try:
                    results = future.result(timeout=0.8)
                    self.assertEqual([r.name for r in results], ["Saki"])
                    self.assertTrue(any(p.results == 1 and p.completed == 0 for p in progress))
                    phrase = "stopped waiting" if finish_early else "time limit"
                    self.assertTrue(any(phrase in notice for notice in results.notices))
                    # Returning results must not depend on releasing the slow engine.
                    self.assertFalse(release.is_set())
                finally:
                    release.set()
                    future.result(timeout=2)

    def test_deadline_keeps_fast_engine_rows_from_an_incomplete_provider(self):
        self._partial_search()

    def test_show_results_now_returns_ready_rows_without_waiting(self):
        self._partial_search(finish_early=True)

    def test_cancel_returns_promptly_and_does_not_start_queued_engine_calls(self):
        release, started, cancelled = threading.Event(), threading.Event(), threading.Event()
        def slow(_query):
            started.set()
            release.wait(2)
            return []
        queued = Mock(return_value=[])
        provider = fixture_provider("anime", slow)
        with patch.object(type(provider), "_init_engines", lambda self: [
            SearchEngine("Slow", "", slow), SearchEngine("Queued", "", queued)]), \
             patch("torrent_finder.providers.combined_provider._REQUEST_LIMIT", 1):
            combined = CombinedProvider([provider])
            combined.restore({})
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(combined.search_many, ["Saki"], cancel_event=cancelled)
                try:
                    self.assertTrue(started.wait(0.5))
                    cancelled.set()
                    future.result(timeout=0.5)
                    queued.assert_not_called()
                finally:
                    release.set()
                    future.result(timeout=2)

    def test_mirror_retry_chain_obeys_one_engine_budget(self):
        from torrent_finder import libgen
        clock = [0.0]
        def timeout(*_args, **_kwargs):
            clock[0] += 7
            raise requests.Timeout("fixture")
        with patch("torrent_finder.search_control.time.monotonic", side_effect=lambda: clock[0]), \
             patch("torrent_finder.libgen.requests.get", side_effect=timeout) as request:
            control = SearchControl(30)
            with self.assertRaises(SearchInterrupted):
                control.run_engine("books", "Libgen", lambda: libgen.search("Saki"), threading.Semaphore(1))
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[0].kwargs["timeout"], (3, 6))
        self.assertEqual(request.call_args_list[1].kwargs["timeout"], (2.5, 2.5))
        self.assertEqual(control.timeouts(), {("books", "Libgen")})

    def test_request_deadlines_do_not_leak_into_normal_searches_or_downloads(self):
        request = Mock()
        search_request(request, "https://example.invalid", timeout=45)
        request.assert_called_once_with("https://example.invalid", timeout=45)

    def test_search_listener_distinguishes_view_results_from_cancel(self):
        from torrent_finder.utils import start_esc_listener
        for key in (b"\r", b"\x1b"):
            with self.subTest(key=key):
                finish, cancel = threading.Event(), threading.Event()
                keyboard = Mock()
                keyboard.kbhit.return_value = True
                keyboard.getch.return_value = key
                with patch("platform.system", return_value="Windows"), \
                     patch.dict("sys.modules", {"msvcrt": keyboard}), \
                     patch("torrent_finder.utils.threading.Thread") as worker:
                    start_esc_listener(cancel, finish_event=finish)
                    worker.call_args.kwargs["target"]()
                self.assertEqual(finish.is_set(), key == b"\r")
                self.assertEqual(cancel.is_set(), key == b"\x1b")
