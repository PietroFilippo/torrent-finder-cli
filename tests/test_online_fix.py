"""Online-Fix searches: only real results, cooldowns as retryable failures, one paced gate."""

import threading
import time
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

from torrent_finder import online_fix, search_control
from torrent_finder.search_control import SearchControl, SearchInterrupted
from torrent_finder.search_errors import SearchError

# Shapes copied from pages online-fix.me served during the October 2026 audit.
SIDEBAR = ('<div class="horizontal-slider"><div class="title">Популярное</div>'
           '<a href="https://online-fix.me/games/survival/18260-palworld-po-seti.html">'
           '<img alt="Palworld по сети"></a>'
           '<a href="https://online-fix.me/games/rpg/17748-elden-ring-po-seti.html"><img alt="Elden Ring по сети"></a></div>')
COOLDOWN = ('<div class="content"><noindex><div class="errors"><div class="title">Информация</div>'
            '<div class="description"> Вы сможете воспользоваться поиском через 10 секунд. </div></div></noindex>'
            + SIDEBAR + '</div>')


def result_block(post_id, slug, title):
    url = f"https://online-fix.me/games/survival/{post_id}-{slug}.html"
    return (f'<div class="news news-search"><div class="article clr"><a class="big-link" href="{url}"></a>'
            f'<div class="image"><a class="img" href="{url}"><img data-src="poster.jpg" alt="{title}"></a></div>'
            f'<a href="{url}"><h2 class="title"> {title} </h2></a></div></div>')


def search_page(*blocks):
    message = '<div class="message"> По Вашему запросу найдены материалы : </div>' if blocks else ""
    return '<form id="fullsearch"></form>' + message + "".join(blocks) + SIDEBAR


class Response:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status


class OnlineFixSearchTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        for target, value in (("_anon_http", Mock(return_value=self.session)), ("_last_search", 0.0),
                              ("_recent", {})):
            patcher = patch.object(online_fix, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.waits = patch.object(online_fix, "search_wait", return_value=True).start()
        self.addCleanup(patch.stopall)

    def serve(self, *pages):
        self.session.get.side_effect = [page if isinstance(page, Response) else Response(page) for page in pages]

    def test_results_come_only_from_result_blocks(self):
        self.serve(search_page(result_block(18260, "palworld-po-seti", "Palworld по сети")))
        rows = online_fix.search("Palworld")
        self.assertEqual([(r.name, r.info_hash) for r in rows], [("Palworld по сети", "18260")])
        self.serve(search_page(result_block(17365, "lethal-company-po-seti", "Lethal Company по сети")))
        self.assertEqual([r.name for r in online_fix.search("Elden Ring")], [])  # sidebar ignored

    def test_cooldown_page_never_becomes_a_sidebar_result(self):
        self.serve(COOLDOWN, COOLDOWN)
        with self.assertRaisesRegex(SearchError, "Press r to retry"):
            online_fix.search("Palworld")

    def test_cooldown_is_waited_out_once_then_searched_again(self):
        self.serve(COOLDOWN, search_page(result_block(18260, "palworld-po-seti", "Palworld по сети")))
        self.assertEqual([r.name for r in online_fix.search("Palworld")], ["Palworld по сети"])
        self.assertEqual(self.waits.call_args.args[0], 10.5)

    def test_cooldown_that_does_not_fit_is_a_retryable_failure(self):
        self.waits.return_value = False
        online_fix._last_search = time.monotonic()  # a search just happened
        with self.assertRaisesRegex(SearchError, "one search every 10 seconds"):
            online_fix.search("Palworld")
        self.session.get.assert_not_called()

    def test_empty_search_is_empty_and_odd_pages_are_failures(self):
        self.serve(search_page())
        self.assertEqual(online_fix.search("Nothing like this"), [])
        for page in (Response("<html><h1>404 Not Found</h1></html>", 404),
                     Response("<html>Just a moment... challenge-platform</html>", 403),
                     "<html><body>Something else entirely</body></html>"):
            online_fix._recent.clear()
            with self.subTest(page=getattr(page, "status_code", 200)):
                self.serve(page)
                with self.assertRaises(SearchError):
                    online_fix.search("Raft")

    def test_both_game_providers_share_one_request_and_searches_are_spaced(self):
        page = search_page(result_block(17365, "lethal-company-po-seti", "Lethal Company по сети"))
        self.session.get.side_effect = lambda *a, **k: (time.sleep(0.05), Response(page))[1]
        found = []
        threads = [threading.Thread(target=lambda: found.append(online_fix.search("Lethal Company")))
                   for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        self.assertEqual(self.session.get.call_count, 1)
        self.assertEqual([[r.name for r in rows] for rows in found], [["Lethal Company по сети"]] * 2)
        self.waits.assert_not_called()

        online_fix.search("Valheim")  # a different game right after: waits for the site's spacing
        self.assertEqual(self.session.get.call_count, 2)
        self.assertGreater(self.waits.call_args.args[0], 9)


class EmptySearchHintTests(unittest.TestCase):
    """A nothing-found multi-word Online-Fix search suggests one distinctive word."""

    def run_search(self, provider_class, query, online_fix_rows=(), other_rows=()):
        from torrent_finder.search_result import SearchResult
        from torrent_finder.search_session import search_many
        rows = [SearchResult(name=name, info_hash=str(n) * 40, source="Apibay") for n, name in enumerate(other_rows, 1)]
        with patch.object(online_fix, "search", return_value=list(online_fix_rows)), ExitStack() as stack:
            # search_many builds a fresh provider, so the other sources are stubbed on the class.
            for name in ("_search_apibay", "_search_fitgirl", "_search_knaben", "_search_solidtorrents"):
                if hasattr(provider_class, name):
                    stack.enter_context(patch.object(provider_class, name,
                                                     return_value=rows if name == "_search_apibay" else []))
            return search_many(provider_class(), [query])

    def test_hint_only_when_nothing_was_found_for_a_multi_word_title(self):
        from torrent_finder.providers.game_provider import GameProvider
        from torrent_finder.providers.online_fix_provider import OnlineFixProvider
        hint = "try one distinctive word"
        for provider_class in (OnlineFixProvider, GameProvider):
            with self.subTest(provider=provider_class.__name__):
                results = self.run_search(provider_class, "Don't Starve Together")
                self.assertEqual(len(results), 0)
                self.assertTrue(any(hint in notice for notice in results.notices))
                self.assertFalse(any(hint in n for n in self.run_search(provider_class, "Starve").notices))
        with_other = self.run_search(GameProvider, "Don't Starve Together", other_rows=["Don't Starve Together"])
        self.assertFalse(any(hint in n for n in with_other.notices))  # other sources answered


class SearchWaitTests(unittest.TestCase):
    """The pacing pause respects the engine budget, Esc and Enter."""

    def run_engine(self, operation, cancel=None):
        control = SearchControl(30, cancel_event=cancel)
        return control.run_engine("online-fix", "Online-Fix", operation, threading.Semaphore(1))

    def test_pause_runs_only_when_a_request_still_fits(self):
        self.assertTrue(self.run_engine(lambda: search_control.search_wait(0.2)))
        started = time.monotonic()
        self.assertFalse(self.run_engine(lambda: search_control.search_wait(11)))
        self.assertLess(time.monotonic() - started, 1)  # declined without pausing

    def test_cancelling_ends_the_pause(self):
        cancel = threading.Event()
        threading.Timer(0.2, cancel.set).start()
        started = time.monotonic()
        with self.assertRaises(SearchInterrupted):
            self.run_engine(lambda: search_control.search_wait(5), cancel)
        self.assertLess(time.monotonic() - started, 2)


if __name__ == "__main__":
    unittest.main()
