"""Credential and RuTracker fixes from the 2026-10-04 final review."""

import threading
import unittest
from unittest.mock import Mock, patch
from urllib.parse import unquote_to_bytes

import isolation  # noqa: F401  (redirects the credential file to a temporary folder)
from torrent_finder import credentials, madokami, rutracker, store
from torrent_finder.search_errors import SearchError


class Page:
    def __init__(self, text, status=200, url="https://rutracker.org/forum/viewtopic.php?t=1"):
        self.text, self.status_code, self.url, self.headers = text, status, url, {}


class RuTrackerCase(unittest.TestCase):
    def setUp(self):
        for name, value in (("_session", None), ("_session_credentials", ("user", "secret")),
                            ("_blocked_until", 0.0), ("_blocked_reason", "blocked"), ("_failed_login", "")):
            patcher = patch.object(rutracker, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(rutracker, "rutracker_config", return_value={"username": "user", "password": "secret"})
        patcher.start()
        self.addCleanup(patcher.stop)


class RuTrackerTests(RuTrackerCase):
    def test_passwords_cp1251_lacks_are_sent_as_character_references(self):
        sent = {}

        def post(url, data=None, **_):
            sent["body"] = data
            return Page("<form><input name='login_username'></form>")
        with patch.object(rutracker.requests, "Session") as session_class:
            session_class.return_value.post.side_effect = post
            session_class.return_value.cookies.get_dict.return_value = {}
            self.assertEqual(rutracker._login("user", "coração€")[1], "rejected")  # no crash
        password = dict(part.split("=") for part in sent["body"].split("&"))["login_password"]
        self.assertEqual(unquote_to_bytes(password), b"cora&#231;&#227;o\x88")  # cp1251 has the euro sign

    def test_the_backoff_also_covers_an_existing_session(self):
        rutracker._session = Mock()
        rutracker._blocked_until = rutracker.time.monotonic() + 300
        with self.assertRaises(SearchError) as caught:
            rutracker._get_session()
        self.assertEqual(caught.exception.status, "blocked")

    def test_a_captcha_waits_a_while_instead_of_for_good(self):
        rutracker._session_credentials = None
        with patch.object(rutracker, "_login", side_effect=[(None, "captcha"), (Mock(), "ok")]) as login:
            for _ in range(2):
                with self.assertRaises(SearchError) as caught:
                    rutracker._get_session()
                self.assertIn("tries again in a few minutes", str(caught.exception))
            self.assertEqual(login.call_count, 1)
            rutracker._blocked_until = 0.0  # the pause is over
            self.assertIsNotNone(rutracker._get_session())
        self.assertEqual(login.call_count, 2)

    def test_errors_are_new_objects(self):
        self.assertIsNot(rutracker._login_error("blocked"), rutracker._login_error("blocked"))

    def test_an_expired_login_is_renewed_once_when_resolving_a_magnet(self):
        expired, fresh = Mock(), Mock()
        expired.get.return_value = Page("<form>login</form>", url="https://rutracker.org/forum/login.php")
        fresh.get.return_value = Page('<a href="magnet:?xt=urn:btih:' + "A" * 40 + '">magnet</a>')
        rutracker._session = expired
        with patch.object(rutracker, "_login", return_value=(fresh, "ok")) as login:
            self.assertEqual(rutracker.resolve_info_hash("1"), "a" * 40)
        self.assertEqual(login.call_count, 1)


class MadokamiAuthTests(unittest.TestCase):
    def test_non_latin1_passwords_do_not_crash_verification(self):
        response = Mock(status_code=200)
        with patch.object(madokami.requests, "get", return_value=response) as get:
            self.assertEqual(madokami.test_credentials("user", "senha€"), (True, "Login successful"))
        self.assertEqual(get.call_args.kwargs["auth"], (b"user", "senha€".encode("utf-8")))


class CredentialScreenTests(unittest.TestCase):
    def test_a_verifier_error_is_reported_not_raised(self):
        from torrent_finder.ui import credentials as screen
        meta = Mock()
        meta.effective_values.return_value = {"MADOKAMI_USERNAME": "u", "MADOKAMI_PASSWORD": "p"}
        meta.missing_required.return_value = []
        meta.verify.side_effect = UnicodeEncodeError("latin-1", "€", 0, 1, "ordinal not in range")
        with patch.object(screen, "console") as console, patch.object(screen.readchar, "readkey"), \
             patch.object(screen, "save_credentials", create=True), \
             patch.object(screen, "arrow_select", return_value=None, create=True):
            try:
                screen._finalize_credentials_save(meta, {"MADOKAMI_PASSWORD": "p"})
            except UnicodeEncodeError:
                self.fail("a verifier error escaped the credentials screen")
        printed = " ".join(str(call.args[0]) for call in console.print.call_args_list if call.args)
        self.assertIn("Couldn't verify (UnicodeEncodeError)", printed)


class CredentialFileLockTests(unittest.TestCase):
    def test_saves_wait_for_another_window_holding_the_file(self):
        held, release = threading.Event(), threading.Event()

        def other_window():
            with store._file_lock(str(credentials._CRED_FILE), 5):
                held.set()
                release.wait(5)
        thread = threading.Thread(target=other_window)
        thread.start()
        try:
            self.assertTrue(held.wait(5))
            with patch.object(store, "LOCK_TIMEOUT", 0.2), self.assertRaises(store.SaveError):
                credentials.save_credentials({"MADOKAMI_USERNAME": "someone"})
        finally:
            release.set()
            thread.join(5)


if __name__ == "__main__":
    unittest.main()
