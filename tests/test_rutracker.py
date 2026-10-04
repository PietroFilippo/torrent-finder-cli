"""RuTracker says why it can't search, and stops repeating logins that can't work."""

import unittest
from unittest.mock import Mock, patch

import requests

from torrent_finder import rutracker
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.base import SearchEngine
from torrent_finder.providers.rutracker_provider import RuTrackerProvider
from torrent_finder.search_errors import SearchError
from torrent_finder.search_result import SearchResult
from torrent_finder.search_session import SearchSession

# What rutracker.org/forum/login.php returned to a script in October 2026.
CHALLENGE = "<html><head><title>Just a moment...</title></head><body>cf-chl ... challenge-platform</body></html>"


class Page:
    def __init__(self, text="", status=200, headers=None, url="https://rutracker.org/forum/login.php"):
        self.text, self.status_code, self.headers, self.url = text, status, headers or {}, url
        self.encoding = "utf-8"


def login_with(page=None, cookies=None, error=None):
    session = Mock()
    session.cookies.get_dict.return_value = cookies or {}
    session.post.side_effect = error if error else (lambda *a, **k: page)
    with patch.object(rutracker.requests, "Session", return_value=session):
        return rutracker._login("user", "secret")


class LoginOutcomeTests(unittest.TestCase):
    def test_each_login_response_is_told_apart(self):
        cases = {
            "ok": dict(page=Page("<html>index</html>"), cookies={"bb_session": "1"}),
            "blocked": dict(page=Page(CHALLENGE, 403)),
            "captcha": dict(page=Page('<form><input name="cap_sid"></form>')),
            "rejected": dict(page=Page('<form><input name="login_username"></form>')),
            "unexpected": dict(page=Page("<html>Server error</html>", 500)),
            "unreachable": dict(error=requests.ConnectionError("down")),
        }
        for reason, response in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(login_with(**response)[1], reason)
        header_only = Page("<html></html>", 403, headers={"cf-mitigated": "challenge"})
        self.assertEqual(login_with(page=header_only)[1], "blocked")
        normal_page_with_script = Page('<form><input name="login_username"></form> challenge-platform', 200)
        self.assertEqual(login_with(page=normal_page_with_script)[1], "rejected")

    def test_credentials_menu_says_when_nothing_was_tested(self):
        with patch.object(rutracker, "_login", return_value=(None, "blocked")):
            ok, message = rutracker.test_credentials("user", "secret")
        self.assertIsNone(ok)
        self.assertIn("credentials not tested", message)


class LoginBackoffTests(unittest.TestCase):
    def setUp(self):
        for name, value in (("_session", None), ("_session_credentials", None), ("_blocked_until", 0.0),
                            ("_failed_login", "")):
            patcher = patch.object(rutracker, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.config = patch.object(rutracker, "rutracker_config",
                                   return_value={"username": "user", "password": "secret"}).start()
        self.addCleanup(patch.stopall)

    def test_cloudflare_block_is_not_retried_for_a_while(self):
        with patch.object(rutracker, "_login", return_value=(None, "blocked")) as login:
            for _ in range(3):  # e.g. three queries of one search
                with self.assertRaises(SearchError) as caught:
                    rutracker._get_session()
                self.assertEqual(caught.exception.status, "blocked")
                self.assertIn("not a password problem", str(caught.exception))
            self.assertEqual(login.call_count, 1)
            rutracker._blocked_until = 0.0  # the pause is over
            with self.assertRaises(SearchError):
                rutracker._get_session()
            self.assertEqual(login.call_count, 2)

    def test_rejected_credentials_wait_until_they_change(self):
        with patch.object(rutracker, "_login", side_effect=[(None, "rejected"), (Mock(), "ok")]) as login:
            for _ in range(2):
                with self.assertRaises(SearchError) as caught:
                    rutracker._get_session()
                self.assertEqual(caught.exception.status, "rejected_login")
            self.assertEqual(login.call_count, 1)  # repeating a bad password invites RuTracker's captcha
            self.config.return_value = {"username": "user", "password": "fixed"}
            self.assertIsNotNone(rutracker._get_session())
            self.assertEqual(login.call_count, 2)

    def test_a_challenge_on_search_is_reported_as_blocked(self):
        session = Mock()
        session.get.return_value = Page(CHALLENGE, 403, url="https://rutracker.org/forum/tracker.php")
        rutracker._session, rutracker._session_credentials = session, ("user", "secret")
        with self.assertRaises(SearchError) as caught:
            rutracker.search("Saki")
        self.assertEqual(caught.exception.status, "blocked")
        self.assertGreater(rutracker._blocked_until, 0)


class FixtureAnime(AnimeProvider):
    def _init_engines(self):
        return [SearchEngine("Nyaa", "", lambda query: [SearchResult(name="Saki 01", info_hash="a" * 40,
                                                                         source="Nyaa")])]


class BlockedInSearchTests(unittest.TestCase):
    def test_blocked_rutracker_is_explained_and_other_results_stay(self):
        blocked = rutracker._login_error("blocked")
        with patch.object(rutracker, "_get_session", side_effect=blocked):
            results = SearchSession([RuTrackerProvider(), FixtureAnime()], ["Saki"], combined=True).run()
        self.assertEqual([r.name for r in results], ["Saki 01"])
        diagnostic = next(d for d in results.session.diagnostics if d.engine == "RuTracker")
        self.assertEqual(diagnostic.status, "blocked")
        self.assertFalse(diagnostic.retryable)  # r can't pass a browser check
        self.assertIn(str(blocked), results.notices)


if __name__ == "__main__":
    unittest.main()
