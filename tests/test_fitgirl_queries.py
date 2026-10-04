"""Game searches find the canonical post despite how the title was typed (P02/P04).

The fixture pages copy the shape of live FitGirl search pages: a search for
"Baldurs Gate 3" returns digest posts around "Baldur’s Gate 3: Digital Deluxe
Edition", and "Civilization VI" is titled "Civilization 6" on the site.
"""

import threading
import time
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import requests

import isolation  # noqa: F401  (keeps the user's settings out of reach)
from torrent_finder import fitgirl, online_fix
from torrent_finder.result_view import game_title_query, matches_name, number_variant, possessive_variant
from torrent_finder.search_control import SharedResults


def post(post_id, title, category="lossless-repack"):
    return (f'<article id="post-{post_id}" class="post category-{category}"><h1 class="entry-title">'
            f'<a href="https://fitgirl-repacks.site/{post_id}/">{title}</a></h1></article>')


DIGEST = post(1, "Updates Digest for October 2026", "uncategorized")
BALDUR = post(2, "Baldur&#8217;s Gate 3: Digital Deluxe Edition &#8211; v4.1.1 + DLC")


class Response:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FitGirlCase(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.pages = {}
        self.session.get.side_effect = lambda url, params=None, **_: Response(self.pages.get(params["s"], ""))
        for target, value in (("_http", Mock(return_value=self.session)), ("_shared", SharedResults(30.0))):
            patcher = patch.object(fitgirl, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def searched(self):
        return [call.kwargs["params"]["s"] for call in self.session.get.call_args_list]


class FitGirlQueryTests(FitGirlCase):
    def test_typed_apostrophe_or_not_finds_the_curly_apostrophe_post(self):
        for query in ("Baldurs Gate 3", "Baldur's Gate 3", "Baldur’s Gate 3"):
            with self.subTest(query=query):
                self.pages = {query: DIGEST + BALDUR}
                rows = fitgirl.search(query)
                self.assertEqual([r.name for r in rows], ["Baldur’s Gate 3: Digital Deluxe Edition – v4.1.1 + DLC"])
                self.assertEqual(self.searched()[-1], query)

    def test_source_and_platform_words_are_not_searched(self):
        self.pages = {"Cyberpunk 2077": post(3, "Cyberpunk 2077: Ultimate Edition &#8211; v2.3"),
                      "Stardew Valley": post(4, "Stardew Valley &#8211; v1.6.0 Build 24079")}
        self.assertEqual(len(fitgirl.search("Cyberpunk 2077 fitgirl")), 1)
        self.assertEqual(len(fitgirl.search("Stardew Valley linux")), 1)
        self.assertEqual(self.searched(), ["Cyberpunk 2077", "Stardew Valley"])

    def test_number_written_the_other_way_is_tried_once_when_nothing_matches(self):
        self.pages = {"Grand Theft Auto V": post(5, "Grand Theft Auto V: Premium Edition &#8211; v1.0"),
                      "Civilization 6": post(6, "Sid Meier&#8217;s Civilization 6: Anthology"),
                      "Civilization VI": post(7, "Sid Meier&#8217;s Civilization VII: Settler&#8217;s Edition")}
        self.assertEqual([r.name for r in fitgirl.search("Grand Theft Auto 5")],
                         ["Grand Theft Auto V: Premium Edition – v1.0"])
        # VII is a different game: it does not count as a match for VI.
        self.assertEqual([r.name for r in fitgirl.search("Civilization VI")], ["Sid Meier’s Civilization 6: Anthology"])
        self.assertEqual(self.searched(), ["Grand Theft Auto 5", "Grand Theft Auto V", "Civilization VI", "Civilization 6"])

    def test_spelled_out_numbers_are_left_to_the_session_retry(self):
        self.assertEqual(fitgirl.search("Dying Light Two"), [])
        self.assertEqual(self.searched(), ["Dying Light Two"])  # the session then searches "Dying Light 2"

    def test_an_error_page_is_a_failure_and_is_not_reused(self):
        self.session.get.side_effect = lambda url, params=None, **_: Response("<h1>Service Unavailable</h1>", 503)
        with self.assertRaises(requests.HTTPError):
            fitgirl.search("Celeste")
        self.session.get.side_effect = lambda url, params=None, **_: Response(post(11, "Celeste"))
        self.assertEqual([r.name for r in fitgirl.search("Celeste")], ["Celeste"])

    def test_possessive_stem_search_keeps_only_posts_matching_the_typed_title(self):
        self.pages = {"Baldur Gate 3": DIGEST + BALDUR + post(8, "Baldur Gate 3 Fan Remake Tools")}
        rows = fitgirl.search("Baldurs Gate 3")
        self.assertEqual([r.name for r in rows], ["Baldur’s Gate 3: Digital Deluxe Edition – v4.1.1 + DLC"])
        self.assertEqual(self.searched(), ["Baldurs Gate 3", "Baldurs Gate III", "Baldur Gate 3"])

    def test_a_title_found_first_time_sends_no_fallbacks(self):
        self.pages = {"Dying Light Two": post(9, "Dying Light Two Fan Edition")}
        fitgirl.search("Dying Light Two")
        self.assertEqual(self.searched(), ["Dying Light Two"])

    def test_nothing_found_ends_after_two_fallbacks(self):
        self.assertEqual(fitgirl.search("Dragons Quest 11"), [])
        self.assertEqual(self.searched(), ["Dragons Quest 11", "Dragons Quest XI", "Dragon Quest 11"])

    def test_a_failed_first_request_is_a_failure_not_an_empty_result(self):
        self.session.get.side_effect = requests.ConnectionError("offline")
        with self.assertRaises(requests.ConnectionError):
            fitgirl.search("Hades")
        self.session.get.side_effect = lambda url, params=None, **_: Response(post(10, "Hades"))
        self.assertEqual([r.name for r in fitgirl.search("Hades")], ["Hades"])  # the failure was not remembered


class SharedFitGirlTests(FitGirlCase):
    def test_both_game_providers_share_one_search(self):
        from torrent_finder.providers.combined_provider import CombinedProvider
        from torrent_finder.providers.fitgirl_provider import FitGirlProvider
        from torrent_finder.providers.game_provider import GameProvider

        def slow_page(url, params=None, **_):
            time.sleep(0.2)  # the second provider asks while the first request is in flight
            return Response(DIGEST + BALDUR)

        self.session.get.side_effect = slow_page
        combined = CombinedProvider([GameProvider(), FitGirlProvider()])
        combined.restore({})
        with ExitStack() as stack:
            for name in ("_search_apibay", "_search_online_fix", "_search_knaben", "_search_solidtorrents"):
                stack.enter_context(patch.object(GameProvider, name, return_value=[]))
            results = combined.search("Baldurs Gate 3 fitgirl")
        self.assertEqual(self.session.get.call_count, 1)
        self.assertEqual([r.name for r in results], ["Baldur’s Gate 3: Digital Deluxe Edition – v4.1.1 + DLC"])
        fitgirl_engines = [d.status for d in results.session.diagnostics if d.engine == "FitGirl"]
        self.assertEqual(fitgirl_engines, ["results", "results"])  # each provider kept its own row

    def test_the_same_query_is_reused_briefly(self):
        self.pages = {"Hades": post(11, "Hades")}
        fitgirl.search("Hades")
        fitgirl.search("hades  PC")  # the same title once source words are dropped
        self.assertEqual(self.session.get.call_count, 1)
        fitgirl._shared.seconds = 0
        fitgirl.search("Hades")
        self.assertEqual(self.session.get.call_count, 2)

    def test_concurrent_identical_searches_send_one_request(self):
        shared = SharedResults(30.0)
        started, release = threading.Event(), threading.Event()
        calls = []

        def search(query):
            calls.append(query)
            started.set()
            release.wait(2)
            return [query]

        found = []
        first = threading.Thread(target=lambda: found.append(shared.run("Hades", search)))
        first.start()
        self.assertTrue(started.wait(2))
        second = threading.Thread(target=lambda: found.append(shared.run("hades", search)))
        second.start()
        time.sleep(0.15)
        release.set()
        first.join(2)
        second.join(2)
        self.assertEqual(calls, ["Hades"])
        self.assertEqual(found, [["Hades"], ["Hades"]])


class OnlineFixQueryTests(unittest.TestCase):
    def test_online_fix_searches_the_title_without_source_words(self):
        session = Mock()
        session.get.return_value = Response('<form id="fullsearch"></form>')
        with patch.object(online_fix, "_anon_http", return_value=session), \
             patch.object(online_fix, "_last_search", 0.0), patch.object(online_fix, "_recent", {}):
            online_fix.search("Palworld online-fix")
        self.assertEqual(session.get.call_args.kwargs["params"]["story"], "Palworld")


class GameQueryHelperTests(unittest.TestCase):
    def test_game_title_query(self):
        for typed, title in (("Cyberpunk 2077 fitgirl", "Cyberpunk 2077"), ("Stardew Valley linux", "Stardew Valley"),
                             ("Palworld online-fix", "Palworld"), ("Elden Ring PC repack", "Elden Ring"),
                             ("Fit Girl Hades", "Hades"), ("Windows", "Windows"), ("Pacific Drive", "Pacific Drive")):
            with self.subTest(typed=typed):
                self.assertEqual(game_title_query(typed), title)

    def test_number_variant(self):
        for typed, variant in (("Dying Light Two", None), ("Civilization VI", "Civilization 6"),
                               ("Final Fantasy 7", "Final Fantasy VII"), ("Grand Theft Auto 5", "Grand Theft Auto V"),
                               ("Final Fantasy 10", "Final Fantasy X"), ("Cyberpunk 2077", None),
                               ("Mega Man X", None), ("Two", None)):
            with self.subTest(typed=typed):
                self.assertEqual(number_variant(typed), variant)

    def test_possessive_variant(self):
        self.assertEqual(possessive_variant("Baldur's Gate 3"), "Baldur Gate 3")
        self.assertEqual(possessive_variant("Baldurs Gate 3"), "Baldur Gate 3")
        self.assertIsNone(possessive_variant("Stardew Valley"))

    def test_matching_ignores_apostrophes_both_ways(self):
        self.assertTrue(matches_name("Baldur’s Gate 3: Deluxe", "Baldurs Gate 3"))
        self.assertTrue(matches_name("Baldurs.Gate.3", "Baldur's Gate 3"))
        self.assertTrue(matches_name("Baldur.s.Gate.3", "Baldur's Gate 3"))
        self.assertFalse(matches_name("Baldur Gate 3", "Baldurs Gate 3"))


if __name__ == "__main__":
    unittest.main()
