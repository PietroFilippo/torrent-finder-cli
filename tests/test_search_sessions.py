import io
import threading
import time
import unittest
from unittest.mock import Mock, patch

import readchar
import requests
from rich.console import Console

from torrent_finder.filters import FilterConfig, FilterPreset
from torrent_finder.name_rules import NameRules
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.providers.combined_provider import CombinedProvider
from torrent_finder.search_session import PageRows, SearchSession
from torrent_finder.search_result import SearchResult
from torrent_finder.search_control import search_request
from torrent_finder.ui import table


def row(name="Example", number=1, **extra):
    return SearchResult(name=name, info_hash=f"{number:040x}", source="Nyaa", **extra)


class FixtureProvider(BaseProvider):
    name = "Fixture"
    slug = "anime"
    icon = ""
    categories = []

    def _init_engines(self):
        return []


class SearchSessionTests(unittest.TestCase):
    def provider(self, *engines):
        p = FixtureProvider()
        p.engines = list(engines)
        return p

    def test_retry_only_failed_query_engine_and_retains_success(self):
        good = Mock(return_value=[row(number=1)])
        flaky = Mock(side_effect=[requests.Timeout(), [row(number=1), row("Other", 2)]])
        p = self.provider(SearchEngine("Good", "", good), SearchEngine("Flaky", "", flaky))
        results = p.search("Example")
        self.assertEqual(len(results), 1)
        self.assertTrue(results.session.can_retry)
        self.assertEqual(results.session.diagnostics[1].status, "timeout")
        retried = results.session.run("retry")
        self.assertEqual(len(retried), 2)
        self.assertEqual(good.call_count, 1)
        self.assertEqual(flaky.call_count, 2)
        self.assertFalse(results.session.can_retry)

    def test_filter_counts_explain_first_exclusion_and_preferences_keep_rows(self):
        p = self.provider(SearchEngine("Fixture", "", lambda q: [
            row("Keep sample 1080p", 1, seeders=10), row("Keep 720p", 2, seeders=10),
            row("Keep 1080p", 3, seeders=0), row("Keep 1080p cam", 4, seeders=10),
            row("Keep 1080p good", 5, seeders=10), row("Keep 1080p shared", 6, seeders=10)]))
        p.name_rules = NameRules(exclude_words="sample")
        p.default_filters = FilterConfig(min_seeds=1)
        p.active_presets = [FilterPreset("1080p", FilterConfig(quality=["1080p"]))]
        p.preferred_presets = [FilterPreset("4K", FilterConfig(quality=["2160p"]))]
        results = SearchSession([p], ["Keep"], FilterConfig(exclude_keywords=["cam"]),
                                result_filter=lambda r: "shared" not in r.name).run()
        d = results.session.diagnostics[0]
        self.assertEqual((d.raw, d.kept), (6, 1))
        self.assertEqual(dict(d.removed), {"Name rules": 1, "Provider defaults": 1, "Require 1080p": 1,
                                         "CLI filters": 1, "Shared rules / CLI filters": 1})
        self.assertEqual(results[0].name, "Keep 1080p good")

    def test_raw_filtered_results_do_not_trigger_auto(self):
        backup = Mock(return_value=[])
        p = self.provider(SearchEngine("On", "", lambda q: [row()]),
                          SearchEngine("Auto", "", backup, enabled=False, emergency_fallback=True))
        p.active_presets = [FilterPreset("4K", FilterConfig(quality=["2160p"]))]
        results = p.search("Example")
        backup.assert_not_called()
        self.assertEqual([d.status for d in results.session.diagnostics], ["filtered", "skipped"])

    def test_auto_runs_after_empty_primary_and_off_remains_off(self):
        backup, off = Mock(return_value=[row()]), Mock()
        p = self.provider(SearchEngine("On", "", lambda q: []),
                          SearchEngine("Auto", "", backup, enabled=False, emergency_fallback=True),
                          SearchEngine("Off", "", off, enabled=False))
        results = p.search("Example")
        self.assertEqual(len(results), 1)
        backup.assert_called_once_with("Example")
        off.assert_not_called()
        self.assertFalse(results.session.can_retry)

    def test_swallowed_transport_failure_is_not_no_matches(self):
        def fetch(q):
            try:
                search_request(Mock(side_effect=requests.ConnectionError("secret URL")), "https://invalid")
            except requests.RequestException:
                return []
        results = self.provider(SearchEngine("Fixture", "", fetch)).search("Example")
        d = results.session.diagnostics[0]
        self.assertEqual(d.status, "error")
        self.assertEqual(d.requests, 1)
        self.assertNotIn("secret", d.describe())

    def test_partial_request_failure_keeps_rows_and_is_retryable(self):
        def fetch(q):
            try:
                search_request(Mock(side_effect=requests.Timeout()), "https://invalid")
            except requests.RequestException:
                return [row()]
        results = self.provider(SearchEngine("Fixture", "", fetch)).search("Example")
        self.assertEqual(len(results), 1)
        self.assertTrue(results.session.can_retry)
        self.assertIn("retained", results.notices[0])

    def test_deadline_freezes_results_and_late_workers_cannot_mutate_retry(self):
        release = threading.Event()
        calls = []
        def fetch(q):
            calls.append(q)
            if len(calls) == 1:
                release.wait(2)
                return [row("Late stale result", 1)]
            return [row("Retry result", 2)]
        p = self.provider(SearchEngine("Slow", "", fetch))
        session = SearchSession([p], ["Example"])
        try:
            results = session.run(timeout=0.06)
            self.assertEqual(results, [])
            self.assertTrue(session.can_retry)
            fresh = session.run("retry")
            release.set()
            time.sleep(0.03)
            self.assertEqual([r.name for r in fresh], ["Retry result"])
            self.assertEqual([r.name for r in session.snapshot()], ["Retry result"])
        finally:
            release.set()

    def test_cancelled_initial_search_does_not_start_sources(self):
        fetch = Mock()
        cancelled = threading.Event()
        cancelled.set()
        session = SearchSession([self.provider(SearchEngine("Fixture", "", fetch))], ["Example"])
        session.run(cancel_event=cancelled)
        fetch.assert_not_called()
        self.assertTrue(session.can_retry)

    def test_pages_are_explicit_deduplicated_and_failed_page_retries_same_cursor(self):
        page = Mock(side_effect=[requests.Timeout(), PageRows([row(number=1), row("New", 2)], has_more=True),
                                 PageRows([], has_more=False)])
        initial = Mock(return_value=[row(number=1)])
        session = self.provider(SearchEngine("Paged", "", initial, page_fn=page)).search("Example").session
        page.assert_not_called()
        session.run("more")
        self.assertEqual(len(session.snapshot()), 1)
        self.assertFalse(session.can_load_more)
        self.assertTrue(session.can_retry)
        self.assertEqual(len(session.run("retry")), 2)
        session.run("more")
        self.assertFalse(session.can_load_more)
        self.assertEqual([call.args for call in page.call_args_list], [("Example", 1), ("Example", 1), ("Example", 2)])
        self.assertEqual(initial.call_count, 1)

    def test_empty_filtered_page_can_continue_and_keeps_requirements(self):
        page = Mock(side_effect=[PageRows([row("Example 720p", 2)], has_more=True),
                                 PageRows([row("Example 1080p", 3)], has_more=False)])
        p = self.provider(SearchEngine("Paged", "", lambda q: [row("Example 1080p", 1)], page_fn=page))
        p.active_presets = [FilterPreset("1080p", FilterConfig(quality=["1080p"]))]
        session = p.search("Example").session
        self.assertEqual(len(session.run("more")), 1)
        self.assertTrue(session.can_load_more)
        self.assertEqual(len(session.run("more")), 2)
        self.assertEqual(session.diagnostics[1].status, "filtered")

    def test_page_limit_and_repeated_page_are_visible(self):
        page = Mock(return_value=PageRows([row(number=2)], has_more=True))
        session = self.provider(SearchEngine("Paged", "", lambda q: [row()], page_fn=page)).search("Example").session
        session.run("more")
        session.run("more")
        self.assertFalse(session.can_load_more)
        self.assertIn("repeated", session.diagnostics[-1].message)

    def test_disabled_or_unused_auto_sources_never_get_pages(self):
        page = Mock()
        p = self.provider(SearchEngine("On", "", lambda q: [row()]),
                          SearchEngine("Auto", "", lambda q: [], enabled=False, emergency_fallback=True, page_fn=page))
        session = p.search("Example").session
        self.assertFalse(session.can_load_more)
        session.run("more")
        page.assert_not_called()
        self.assertTrue(any("unavailable" in line for line in session.page_status()))

    def test_multi_query_preferred_alias_and_all_origins_survive(self):
        p = self.provider(SearchEngine("On", "", lambda q: [row("Example 1080p" if q == "Alt" else "Example", 1)]))
        p.preferred_presets = [FilterPreset("1080p", FilterConfig(quality=["1080p"]))]
        results = SearchSession([p], ["Example", "Alt"], work_titles={"Alt": "Example"}).run()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Example 1080p")
        self.assertEqual(results[0]["matched_queries"], ["Example", "Alt"])

    def test_table_more_preserves_checked_identity_sort_and_refinement(self):
        p = self.provider(SearchEngine("Paged", "", lambda q: [row("Keep B", 1), row("Drop", 2)],
                                      page_fn=lambda q, page: PageRows([row("Keep A", 3)], has_more=False)))
        results = p.search("Keep")
        keys = iter(["f", " ", "m", readchar.key.ENTER])
        sized = Console(file=io.StringIO(), width=40, height=16)
        with patch.object(table, "console", sized), patch.object(table.readchar, "readkey", side_effect=lambda: next(keys)), \
             patch.object(table, "refine_results", return_value=("Keep", "contains", "name")), \
             patch("torrent_finder.ui.search_diagnostics.run_action", side_effect=lambda s, a: (s.run(a), "")):
            picked = table.interactive_select(results)
        self.assertEqual(picked[0], "one")
        self.assertEqual(results[picked[1]].name, "Keep B")
        self.assertEqual(len(results), 3)

    def test_empty_result_table_can_retry_to_results(self):
        fetch = Mock(side_effect=[requests.Timeout(), [row()]])
        results = self.provider(SearchEngine("Fixture", "", fetch)).search("Example")
        sized = Console(file=io.StringIO(), width=40, height=16)
        with patch.object(table, "console", sized), patch.object(table.readchar, "readkey", side_effect=["r", readchar.key.ENTER]), \
             patch("torrent_finder.ui.search_diagnostics.run_action", side_effect=lambda s, a: (s.run(a), "")):
            picked = table.interactive_select(results)
        self.assertEqual(picked, ("one", 0))
        self.assertEqual(len(results), 1)

    def test_knaben_cursor_uses_source_count_before_hash_filtering(self):
        from torrent_finder import knaben
        response = Mock(status_code=200)
        response.json.return_value = {"hits": [{"title": "Invalid", "hash": None}] * 50}
        with patch.object(knaben.requests, "post", return_value=response) as send:
            rows = knaben.search("Example", [6000000], page=3)
        self.assertEqual(rows, [])
        self.assertTrue(rows.has_more)
        body = send.call_args.kwargs["json"]
        self.assertEqual((body["from"], body["size"]), (100, 50))
        self.assertTrue(body["hide_unsafe"])
        self.assertTrue(body["hide_xxx"])

    def test_knaben_malformed_payload_produces_source_error(self):
        from torrent_finder import knaben
        response = Mock(status_code=200)
        response.json.return_value = {"error": "server"}
        with patch.object(knaben.requests, "post", return_value=response):
            results = self.provider(SearchEngine("Knaben", "", lambda q: knaben.search(q, [6000000]))).search("Example")
        self.assertEqual(results.session.diagnostics[0].status, "error")

    def test_nyaa_page_preserves_query_category_and_reads_next_page_link(self):
        from torrent_finder import nyaa
        response = Mock(status_code=200)
        response.text = '<table class="torrent-list"><tbody></tbody></table><a href="/?q=Example&amp;c=3_3&amp;p=3">Next</a>'
        with patch.object(nyaa.requests, "get", return_value=response) as send:
            rows = nyaa.search_page("Example", "3_3", 2)
        self.assertTrue(rows.has_more)
        self.assertEqual(send.call_args.kwargs["params"], {"q": "Example", "c": "3_3", "p": 2, "s": "id", "o": "desc"})
        response.text = "<html>Challenge page</html>"
        with patch.object(nyaa.requests, "get", return_value=response):
            from torrent_finder.search_errors import SearchError
            with self.assertRaises(SearchError):
                nyaa.search_page("Example", "3_3", 2)

    def test_initial_fetched_timestamp_does_not_advance_when_loading_pages(self):
        p = self.provider(SearchEngine("Paged", "", lambda q: [row(number=1)],
                                      page_fn=lambda q, page: PageRows([row(number=2)], has_more=False)))
        first = p.search("Example")
        before = first[0]["fetched_at"]
        after = first.session.run("more")
        self.assertEqual(next(r["fetched_at"] for r in after if r.info_hash == first[0].info_hash), before)

    def test_pagination_page_cap_does_not_start_an_eleventh_page(self):
        page = Mock(side_effect=lambda q, page: PageRows([row(number=page + 1)], has_more=True))
        session = self.provider(SearchEngine("Paged", "", lambda q: [row()], page_fn=page)).search("Example").session
        for _ in range(11):
            session.run("more")
        self.assertEqual(page.call_count, 10)
        self.assertFalse(session.can_load_more)
        self.assertTrue(any("page limit reached" in line for line in session.page_status()))

    def test_combined_identity_uses_registry_order_across_queries(self):
        first = self.provider(SearchEngine("First", "", lambda q: [row("First origin")] if q == "Alt" else []))
        second = self.provider(SearchEngine("Second", "", lambda q: [row("Second origin")] if q == "Title" else []))
        second.slug = "manga"
        results = SearchSession([first, second], ["Title", "Alt"], combined=True).run()
        self.assertEqual(results[0]["provider_slug"], "anime")
        self.assertEqual(results[0]["matched_providers"], ["anime", "manga"])

    def test_slow_provider_extra_engines_do_not_monopolize_request_queue(self):
        release = threading.Event()
        slow = self.provider(*[SearchEngine(str(i), "", lambda q: release.wait(2) or []) for i in range(6)])
        fast = self.provider(SearchEngine("Fast", "", lambda q: [row()]))
        fast.slug = "manga"
        try:
            results = SearchSession([slow, fast], ["Example"], combined=True).run(timeout=0.08)
            self.assertEqual(len(results), 1)
        finally:
            release.set()

    def test_nyaa_rss_short_page_is_exhausted_and_full_feed_starts_catalog_page_two(self):
        from torrent_finder.providers.anime_provider import AnimeProvider
        p = AnimeProvider()
        p.prefer_title_matches = False
        p.engines = [p.engines[0]]
        response = Mock(status_code=200)
        response.text = '<rss xmlns:nyaa="https://nyaa.si/xmlns/nyaa"><channel><item><title>Example</title><nyaa:infoHash>' + 'a' * 40 + '</nyaa:infoHash></item></channel></rss>'
        with patch("torrent_finder.providers.base.requests.get", return_value=response):
            results = p.search("Example")
        self.assertFalse(results.session.can_load_more)
        self.assertEqual(p.engines[0].initial_page, 1)

    def test_empty_results_redraw_when_terminal_resizes(self):
        results = self.provider(SearchEngine("Empty", "", lambda q: [])).search("Missing")
        sized = Console(file=io.StringIO(), width=100, height=32)
        built_at = []
        original = table.build_table
        def build(*args, **kwargs):
            built_at.append(sized.width)
            return original(*args, **kwargs)
        def resize_then_back():
            time.sleep(0.07)
            sized.width, sized.height = 40, 16
            time.sleep(0.15)
            return readchar.key.ESC
        with patch.object(table, "console", sized), patch.object(table, "build_table", side_effect=build), \
             patch.object(table.readchar, "readkey", side_effect=resize_then_back):
            table.interactive_select(results)
        self.assertGreaterEqual(len(built_at), 2)
        self.assertLessEqual(built_at[-1], 40)  # Rich reserves a cell on legacy Windows consoles
        self.assertGreater(built_at[0], built_at[-1])

    def test_empty_compact_table_reserves_width_for_controls(self):
        sized = Console(file=io.StringIO(), width=40, height=16)
        with patch.object(table, "console", sized):
            rendered = table.build_table([], 0, 0, 0, 0, 0, 1)
            lines = sized.render_lines(rendered, sized.options)
        self.assertLessEqual(len(lines), 12)  # leaves room for heading/status/actions

    def test_still_running_requests_keep_their_slot_across_retry(self):
        release, started = threading.Event(), threading.Event()
        calls = []
        def fetch(query):
            calls.append(query)
            started.set()
            release.wait(1)
            return [row()]
        session = SearchSession([self.provider(SearchEngine("Slow", "", fetch))], ["Example"], workers=1)
        try:
            session.run(timeout=0.06)
            self.assertTrue(started.is_set())
            session.run("retry", timeout=0.06)
            self.assertEqual(calls, ["Example"])
            self.assertGreater(session.diagnostics[0].seconds, 0)
            # The waiting worker may report zero requests before the coordinator
            # reaches its deadline; otherwise the abandoned attempt is unknown.
            self.assertIn(session.diagnostics[0].requests, (0, None))
        finally:
            release.set()


if __name__ == "__main__":
    unittest.main()
