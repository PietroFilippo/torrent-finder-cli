import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from torrent_finder import credentials, madokami, rutracker
from torrent_finder.providers.madokami_provider import MadokamiProvider
from torrent_finder.search_errors import SearchError


class CredentialRecoveryTests(unittest.TestCase):
    def test_legacy_credentials_migrate_without_deleting_source(self):
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory) / "old.json"
            new = Path(directory) / "stable.json"
            data = {"madokami_username": "fixture", "madokami_password": "test-only"}
            old.write_text(json.dumps(data), encoding="utf-8")
            with patch.object(credentials, "_CRED_FILE", new), \
                 patch.object(credentials, "_LEGACY_CRED_PATHS", [str(old)]), \
                 patch.object(credentials, "_file_cache", None):
                self.assertEqual(credentials._load_file(), data)
            self.assertEqual(json.loads(new.read_text()), data)
            self.assertEqual(json.loads(old.read_text()), data)

    def test_cleared_stable_file_does_not_restore_old_passwords(self):
        with tempfile.TemporaryDirectory() as directory:
            old, new = Path(directory) / "old.json", Path(directory) / "stable.json"
            old.write_text('{"madokami_password":"old"}')
            new.write_text('{}')
            with patch.object(credentials, "_CRED_FILE", new), \
                 patch.object(credentials, "_LEGACY_CRED_PATHS", [str(old)]), \
                 patch.object(credentials, "_file_cache", None):
                self.assertEqual(credentials._load_file(), {})

    def test_saving_after_parse_failure_preserves_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            original = b'{"madokami_password":"fixture",'
            path.write_bytes(original)
            with patch.object(credentials, "_CRED_FILE", path), \
                 patch.object(credentials, "_file_cache", None):
                self.assertEqual(credentials._load_file(), {})
                self.assertIn("preserved", credentials.storage_problem())
                with self.assertRaises(ValueError):
                    credentials.save_credentials({"TMDB_API_KEY": "fixture"})
            self.assertEqual(path.read_bytes(), original)

    def test_transient_read_error_is_retried(self):
        with patch.object(credentials, "_migrate_legacy_file"), \
             patch.object(credentials, "_CRED_FILE") as path, \
             patch.object(credentials, "_file_cache", None), \
             patch.object(credentials, "_read_credentials", side_effect=[PermissionError(), {"x": "fixture"}]):
            path.exists.return_value = True
            self.assertEqual(credentials._load_file(), {})
            self.assertEqual(credentials._load_file(), {"x": "fixture"})

    def test_unreadable_legacy_file_cannot_be_overwritten_by_a_new_store(self):
        with tempfile.TemporaryDirectory() as directory:
            old, new = Path(directory) / "old.json", Path(directory) / "stable.json"
            old.write_text('{broken')
            with patch.object(credentials, "_CRED_FILE", new), \
                 patch.object(credentials, "_LEGACY_CRED_PATHS", [str(old)]), \
                 patch.object(credentials, "_file_cache", None):
                self.assertIn("preserved", credentials.storage_problem())
                with self.assertRaises(OSError):
                    credentials.save_credentials({"MADOKAMI_USERNAME": "fixture"})
            self.assertFalse(new.exists())
            self.assertEqual(old.read_text(), '{broken')

    def test_sessions_refresh_after_credentials_change_and_clear(self):
        for module in (madokami, rutracker):
            with self.subTest(provider=module.__name__):
                config = module.__name__.split('.')[-1] + "_config"
                first, second = Mock(), Mock()
                first.auth = ("fixture", "first")
                second.auth = ("fixture", "second")
                with patch.object(module, "_session", None), \
                     patch.object(module, config, side_effect=[
                         {"username": "fixture", "password": "first"},
                         {"username": "fixture", "password": "second"}, None]), \
                     patch.object(module.requests, "Session", side_effect=[first, second]), \
                     patch.object(rutracker, "_session_credentials", None), \
                     patch.object(rutracker, "_post_login", side_effect=[first, second]):
                    self.assertIs(module._get_session(), first)
                    self.assertIs(module._get_session(), second)
                    self.assertIsNone(module._get_session())
                first.close.assert_called_once()
                second.close.assert_called_once()

    def test_missing_login_is_carried_into_the_next_search_screen(self):
        from torrent_finder import main as app
        provider = MadokamiProvider()
        with patch.object(sys, "argv", ["torrent", "-t", "madokami", "-q", "Saki", "--skip-warning"]), \
             patch.object(app, "get_provider", return_value=provider), \
             patch.object(provider, "search", side_effect=SearchError("Madokami: not logged in")), \
             patch.object(app, "advise_limited_terminal"), patch.object(app, "clear_screen"), \
             patch.object(app, "console"), patch.object(app, "start_esc_listener"), \
             patch.object(app, "check_for_update", return_value=None), \
             patch.object(app, "consume_update_report", return_value=""), \
             patch.object(app, "history_queries", return_value=[]), \
             patch.object(app, "make_search_screen_renderer") as renderer, \
             patch.object(app, "get_query_with_shortcut", side_effect=RuntimeError("reached prompt")):
            with self.assertRaisesRegex(RuntimeError, "reached prompt"):
                app._main_loop()
        self.assertIn("Madokami: not logged in", renderer.call_args.kwargs["notice"])

    def test_missing_madokami_login_reaches_search_caller(self):
        with patch.object(madokami, "_get_session", return_value=None), \
             patch.object(credentials, "storage_problem", return_value=""):
            with self.assertRaisesRegex(SearchError, "Madokami: not logged in"):
                MadokamiProvider().search("Saki")

    def test_madokami_rejected_login_is_not_empty_results(self):
        session = Mock()
        session.get.return_value.status_code = 401
        with patch.object(madokami, "_get_session", return_value=session):
            with self.assertRaisesRegex(SearchError, "rejected the login"):
                MadokamiProvider().search("Saki")
