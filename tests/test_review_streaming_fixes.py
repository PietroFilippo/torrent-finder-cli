"""Streaming and input fixes from the 2026-10-04 final review."""

import socket
import subprocess
import unittest
from unittest.mock import Mock, patch

import readchar

import isolation  # noqa: F401  (keeps the user's settings out of reach)
from torrent_finder import downloader
from torrent_finder.ui import prompts


class VlcSessionTests(unittest.TestCase):
    def test_vlc_gets_its_own_session_outside_windows(self):
        with patch.object(downloader, "_build_vlc_cmd", return_value=["vlc", "http://x"]), \
             patch.object(downloader.platform, "system", return_value="Linux"), \
             patch.object(downloader.subprocess, "Popen") as popen:
            downloader._launch_vlc("http://x", None)
        self.assertTrue(popen.call_args.kwargs.get("start_new_session"))


class StreamPortTests(unittest.TestCase):
    def test_a_taken_port_is_replaced_by_a_free_one(self):
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            taken = busy.getsockname()[1]
            port = downloader._stream_port(taken)
        self.assertNotEqual(port, taken)
        with socket.socket() as check:
            check.bind(("127.0.0.1", port))  # really free

    def test_a_free_port_is_kept(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            free = probe.getsockname()[1]
        self.assertEqual(downloader._stream_port(free), free)


class EpisodeKeyTests(unittest.TestCase):
    def test_b_is_not_listened_for_on_the_first_episode(self):
        downloader.platform.system()  # resolved (and cached) before Popen is replaced
        proc = Mock()
        proc.poll.return_value = 0
        proc.wait.return_value = 0
        proc.returncode = 0
        with patch.object(downloader.subprocess, "Popen", return_value=proc), \
             patch.object(downloader, "_start_vlc_hotkey_thread") as hotkeys:
            downloader._run_stream(["backend"], None, allow_navigate=True, allow_back=False)
            first_back = hotkeys.call_args.args[2]
            downloader._run_stream(["backend"], None, allow_navigate=True)
            later_back = hotkeys.call_args.args[2]
        self.assertIsNone(first_back)
        self.assertIsNotNone(later_back)


class CleanupInterruptTests(unittest.TestCase):
    def test_a_second_ctrl_c_during_a_polite_stop_still_kills_the_download(self):
        proc = Mock()
        proc.wait.side_effect = KeyboardInterrupt
        with patch.object(downloader.platform, "system", return_value="Windows"), \
             patch.object(downloader.signal, "CTRL_BREAK_EVENT", 1, create=True), \
             patch.object(downloader, "_kill_process_tree") as kill:
            downloader._cancel_download_proc(proc)
        kill.assert_called_once_with(proc)

    def test_taskkill_runs_in_its_own_group_and_survives_a_second_ctrl_c(self):
        killer = Mock()
        killer.wait.side_effect = [KeyboardInterrupt, 0]
        proc = Mock(pid=4242)
        proc.wait.return_value = 0
        with patch.object(downloader.platform, "system", return_value="Windows"), \
             patch.object(downloader.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True), \
             patch.object(downloader.subprocess, "Popen", return_value=killer) as popen:
            downloader._kill_process_tree(proc)
        self.assertEqual(popen.call_args.args[0], ["taskkill", "/T", "/F", "/PID", "4242"])
        self.assertEqual(popen.call_args.kwargs["creationflags"], 512)
        self.assertEqual(killer.wait.call_count, 2)


class NestedFieldTests(unittest.TestCase):
    def test_ctrl_d_in_a_nested_field_goes_back(self):
        with patch.object(prompts.readchar, "readkey", return_value=readchar.key.CTRL_D), \
             patch("sys.stdout"):
            self.assertEqual(prompts.get_query_with_shortcut("Rename: "), "GO_BACK")
            with self.assertRaises(EOFError):
                prompts.get_query_with_shortcut("Search: ", propagate_interrupt=True)


if __name__ == "__main__":
    unittest.main()
