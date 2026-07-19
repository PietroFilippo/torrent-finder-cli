import threading
import unittest
from contextlib import nullcontext
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rich.console import Console

from torrent_finder import acquisition
from torrent_finder import main as app_main
from torrent_finder import torrent_meta
from torrent_finder.ui import creator, credentials, prompts, selector, table
from torrent_finder.ui.selector import SelectItem


class SelectorCancelTests(unittest.TestCase):
    def test_raised_ctrl_c_is_same_as_esc_in_file_selector(self):
        terminal = StringIO()
        sized_console = Console(
            file=StringIO(),
            width=72,
            height=20,
            color_system=None,
        )

        with patch.object(selector, "console", sized_console), \
             patch.object(selector.sys, "stdout", terminal), \
             patch.object(selector.readchar, "readkey", side_effect=KeyboardInterrupt):
            selected = selector.arrow_select(
                [SelectItem(label="example.mkv", value="example.mkv")],
                title="Select Torrent Files",
            )

        self.assertIsNone(selected)


class ResultsTableCancelTests(unittest.TestCase):
    def test_raised_ctrl_c_is_same_as_esc_in_results_table(self):
        sized_console = Console(
            file=StringIO(),
            width=90,
            height=24,
            color_system=None,
        )
        results = [{
            "name": "Example",
            "source": "Knaben",
            "size": 1024,
            "seeders": 10,
            "leechers": 1,
        }]

        with patch.object(table, "console", sized_console), \
             patch.object(table.readchar, "readkey", side_effect=KeyboardInterrupt):
            selected = table.interactive_select(results)

        self.assertIsNone(selected)


class TorrentFileCancelTests(unittest.TestCase):
    def test_ctrl_c_during_metadata_fetch_returns_to_download_menu(self):
        provider = SimpleNamespace(
            slug="movies",
            supports_subtitles=True,
            supports_episode_picker=True,
            supports_streaming=True,
        )
        result = {
            "name": "Example",
            "info_hash": "a" * 40,
            "seeders": 1,
            "source": "Apibay",
        }
        adapter = Mock()
        adapter.pick.return_value = acquisition.PickOutcome("menu", "magnet:?example")
        session = SimpleNamespace(
            magnet="magnet:?example",
            result=result,
            selected_files=None,
            sub_choice=None,
            fetch_files_meta=Mock(side_effect=KeyboardInterrupt),
        )
        stop_listener = Mock()

        with patch.object(app_main, "interactive_select", side_effect=[("one", 0), None]), \
             patch.object(app_main.acquisition, "for_result", return_value=adapter), \
             patch.object(app_main, "TorrentSession", return_value=session), \
             patch.object(app_main, "download_method_prompt", side_effect=["pick_episodes", "back"]), \
             patch.object(app_main, "has_aria2", return_value=True), \
             patch.object(app_main, "start_esc_listener", return_value=stop_listener), \
             patch.object(app_main.console, "status", return_value=nullcontext()), \
             patch.object(app_main.console, "print"), \
             patch.object(app_main, "clear_screen"), \
             patch.object(app_main, "record_torrent_picked"):
            outcome = app_main.browse_results(provider, [result])

        self.assertEqual(outcome, "back")
        self.assertEqual(session.fetch_files_meta.call_count, 1)
        stop_listener.set.assert_called_once_with()

    def test_ctrl_c_terminates_metadata_child_and_marks_cancelled(self):
        cancel_event = threading.Event()
        proc = Mock()
        proc.poll.return_value = None

        with patch.object(torrent_meta, "has_aria2", return_value=True), \
             patch.object(torrent_meta.subprocess, "Popen", return_value=proc), \
             patch.object(torrent_meta.time, "sleep", side_effect=KeyboardInterrupt):
            metadata = torrent_meta.fetch_file_list(
                "magnet:?xt=urn:btih:" + "a" * 40,
                cancel_event=cancel_event,
            )

        self.assertIsNone(metadata)
        self.assertTrue(cancel_event.is_set())
        proc.terminate.assert_called_once_with()


class ActiveOperationCancelTests(unittest.TestCase):
    def test_ctrl_c_during_acquisition_pick_returns_to_results(self):
        provider = SimpleNamespace(slug="movies")
        result = {
            "name": "Example",
            "info_hash": "a" * 40,
            "seeders": 1,
            "source": "Apibay",
        }
        adapter = Mock()
        adapter.pick.side_effect = KeyboardInterrupt

        with patch.object(app_main, "interactive_select", side_effect=[("one", 0), None]), \
             patch.object(app_main.acquisition, "for_result", return_value=adapter), \
             patch.object(app_main, "clear_screen"), \
             patch.object(app_main, "record_torrent_picked"):
            outcome = app_main.browse_results(provider, [result])

        self.assertEqual(outcome, "back")

    def test_ctrl_c_during_creator_wait_marks_operation_cancelled(self):
        blocker = threading.Event()
        cancel_event = threading.Event()
        stop_listener = Mock()

        with patch.object(creator, "start_esc_listener", return_value=stop_listener), \
             patch.object(creator.console, "status", return_value=nullcontext()), \
             patch.object(creator.time, "sleep", side_effect=KeyboardInterrupt):
            cancelled, value = creator._run_cancellable(
                lambda: blocker.wait(1),
                "Looking up creator",
                cancel=cancel_event,
            )

        self.assertTrue(cancelled)
        self.assertIsNone(value)
        self.assertTrue(cancel_event.is_set())
        stop_listener.set.assert_called_once_with()

    def test_ctrl_c_during_torrent_info_fetch_returns_to_caller(self):
        with patch("torrent_finder.torrent_info.fetch_torrent_info", side_effect=KeyboardInterrupt), \
             patch.object(prompts.console, "status", return_value=nullcontext()), \
             patch.object(prompts.console, "print"):
            prompts.torrent_info_screen({"name": "Example"})

    def test_ctrl_c_during_credential_verification_reopens_form(self):
        meta = Mock()
        meta.effective_values.return_value = {"key": "value"}
        meta.missing_required.return_value = []
        meta.verify.side_effect = KeyboardInterrupt

        with patch.object(credentials.console, "status", return_value=nullcontext()), \
             patch.object(credentials.console, "print"):
            saved = credentials._finalize_credentials_save(meta, {"key": "value"})

        self.assertFalse(saved)
        meta.save.assert_not_called()

    def test_ctrl_c_in_download_menu_returns_to_results(self):
        provider = SimpleNamespace(
            slug="movies",
            supports_subtitles=True,
            supports_episode_picker=True,
            supports_streaming=True,
        )
        result = {
            "name": "Example",
            "info_hash": "a" * 40,
            "seeders": 1,
            "source": "Apibay",
        }
        adapter = Mock()
        adapter.pick.return_value = acquisition.PickOutcome("menu", "magnet:?example")

        with patch.object(app_main, "interactive_select", side_effect=[("one", 0), None]), \
             patch.object(app_main.acquisition, "for_result", return_value=adapter), \
             patch.object(app_main, "download_method_prompt", side_effect=KeyboardInterrupt), \
             patch.object(app_main, "clear_screen"), \
             patch.object(app_main, "record_torrent_picked"):
            outcome = app_main.browse_results(provider, [result])

        self.assertEqual(outcome, "back")


class ExitConfirmationTests(unittest.TestCase):
    def test_whats_next_exit_requires_confirmation(self):
        provider = SimpleNamespace(slug="movies")

        with patch.object(app_main, "search_again_prompt", return_value="exit"), \
             patch("torrent_finder.ui.prompts.confirm_prompt", return_value=True) as confirm:
            outcome = app_main._handle_whats_next(provider)

        self.assertEqual(outcome, "EXIT")
        confirm.assert_called_once()

    def test_declined_whats_next_exit_reopens_menu(self):
        provider = SimpleNamespace(slug="movies")

        with patch.object(app_main, "search_again_prompt", side_effect=[None, "search"]), \
             patch("torrent_finder.ui.prompts.confirm_prompt", return_value=False) as confirm, \
             patch.object(app_main, "clear_screen"):
            outcome = app_main._handle_whats_next(provider)

        self.assertEqual(outcome, (None, provider, None, None))
        confirm.assert_called_once()

    def test_ctrl_c_inside_exit_confirmation_declines_safely(self):
        with patch.object(prompts.readchar, "readkey", side_effect=KeyboardInterrupt), \
             patch.object(prompts.sys, "stdout", StringIO()), \
             patch.object(prompts.console, "print"):
            confirmed = prompts.confirm_prompt("Exit Torrent Finder?", title="Exit")

        self.assertFalse(confirmed)


if __name__ == "__main__":
    unittest.main()
