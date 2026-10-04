"""Follow-ups to the 2026-10-04 review: Esc during lookups, a scoring safety
net, and a manual link for failed Madokami batch items."""

import os
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, Mock, patch

import isolation  # noqa: F401  (keeps the user's settings out of reach)
from torrent_finder import acquisition, libgen, online_fix
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.search_result import SearchResult
from torrent_finder.search_session import SearchSession


def esc_pressed(cancel_event, **_):
    cancel_event.set()
    return threading.Event()


def esc_never(cancel_event, **_):
    return threading.Event()


class WaitWithEscTests(unittest.TestCase):
    def wait(self, listener, work, *args):
        with patch("torrent_finder.utils.start_esc_listener", listener), \
             patch.object(acquisition, "console", MagicMock()):
            return acquisition._wait_with_esc("Looking up…", work, *args)

    def test_esc_leaves_a_slow_lookup_at_once(self):
        release = threading.Event()
        self.addCleanup(release.set)
        self.assertEqual(self.wait(esc_pressed, lambda: release.wait(5)), (None, True))

    def test_a_finished_lookup_returns_its_result(self):
        self.assertEqual(self.wait(esc_never, lambda value: value * 2, 21), (42, False))

    def test_lookup_errors_reach_the_caller(self):
        def broken():
            raise ValueError("bad page")
        with self.assertRaises(ValueError):
            self.wait(esc_never, broken)

    def test_lookups_that_accept_it_get_the_cancel_event(self):
        seen = {}

        def work(md5, cancel_event=None):
            seen["event"] = cancel_event
            return md5
        self.assertEqual(self.wait(esc_never, work, "abc"), ("abc", False))
        self.assertIsInstance(seen["event"], threading.Event)


class LookupCancelTests(unittest.TestCase):
    def test_cancelling_the_libgen_lookup_goes_back_without_downloading(self):
        result = SearchResult(name="Dune", info_hash="libgen:x", source="Libgen", handle={"lg_md5": "x"})
        with patch.object(acquisition, "_wait_with_esc", return_value=(None, True)), \
             patch("torrent_finder.ui.prompts.download_dir_ready", return_value=True), \
             patch.object(libgen, "download_file") as download:
            outcome = acquisition.LibgenAcquisition().pick(result)
        self.assertEqual(outcome.action, "back")
        download.assert_not_called()

    def test_libgen_stops_trying_mirrors_once_cancelled(self):
        cancel = threading.Event()
        calls = []

        def get(url, **_):
            calls.append(url)
            cancel.set()  # Esc while the first mirror answers slowly
            raise libgen.requests.Timeout()
        with patch.object(libgen.requests, "get", side_effect=get):
            self.assertIsNone(libgen.resolve_download_url("x", cancel_event=cancel))
        self.assertEqual(len(calls), 1)

    def test_online_fix_saves_nothing_after_a_cancel(self):
        cancel = threading.Event()
        cancel.set()
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(online_fix, "resolve_torrent", return_value="https://uploads.online-fix.me/t/Game.torrent"), \
             patch.object(online_fix, "_anon_http") as http:
            self.assertIsNone(online_fix.fetch_torrent_for("https://online-fix.me/g/1-x.html", folder, cancel))
            self.assertEqual(os.listdir(folder), [])
        http.return_value.get.assert_not_called()

    def test_cancelling_a_madokami_folder_listing_goes_back(self):
        with patch.object(acquisition, "_wait_with_esc", return_value=(None, True)):
            self.assertEqual(acquisition.MadokamiAcquisition()._choose_files("/Manga/X/XX/XXXX/Series"), [])


class MadokamiBatchTests(unittest.TestCase):
    def test_a_failed_file_offers_the_page_to_grab_manually(self):
        result = SearchResult(name="Series v01", info_hash="madokami:/x/v01.cbz", source="Madokami",
                              page_url="https://manga.madokami.al/x/v01.cbz", handle={"mdk_path": "/x/v01.cbz"})
        with patch("torrent_finder.madokami.download_file", return_value=None):
            outcome = acquisition.MadokamiAcquisition().batch_item(
                result, download_dir="C:/x", cancel_event=threading.Event(), set_status=lambda _: None)
        self.assertEqual((outcome.ok, outcome.manual_url), (False, "https://manga.madokami.al/x/v01.cbz"))


def broken_hint(query):
    raise RuntimeError("hint bug")


class Fixture(BaseProvider):
    name, slug, icon, categories = "Fixture", "fixture", "", []
    prefer_title_matches = True

    def __init__(self, rows, slug="fixture"):
        self.rows, self.slug = rows, slug
        super().__init__()

    def _init_engines(self):
        return [SearchEngine("Engine", "", lambda query: list(self.rows),
                             empty_hint=broken_hint)]


class SafetyNetTests(unittest.TestCase):
    def test_a_scoring_bug_ranks_rows_last_instead_of_losing_them(self):
        provider = Fixture([SearchResult(name="Saki 01", info_hash="a" * 40, source="Nyaa")])
        provider.title_relevance = Mock(side_effect=RuntimeError("scorer bug"))
        results = SearchSession([provider], ["Saki"]).run()
        self.assertEqual([r.name for r in results], ["Saki 01"])
        self.assertIn("Some results could not be ranked (an internal error); they are listed last.", results.notices)

    def test_a_filter_bug_hides_only_that_providers_rows(self):
        good = Fixture([SearchResult(name="Saki 01", info_hash="a" * 40, source="Nyaa")], slug="good")
        broken = Fixture([SearchResult(name="Saki 02", info_hash="b" * 40, source="Nyaa")], slug="broken")
        broken._filter_search_results = Mock(side_effect=RuntimeError("filter bug"))
        broken.filter_with_reasons = Mock(side_effect=RuntimeError("filter bug"))
        results = SearchSession([good, broken], ["Saki"], combined=True).run()
        self.assertEqual([r.name for r in results], ["Saki 01"])
        self.assertTrue(any("could not be filtered" in notice for notice in results.notices))

    def test_a_broken_empty_hint_is_skipped(self):
        results = SearchSession([Fixture([])], ["Nothing"]).run()
        self.assertEqual(list(results), [])


if __name__ == "__main__":
    unittest.main()
