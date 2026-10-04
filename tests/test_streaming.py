"""Streaming owns its player, says how it ended, and prepares cancellably."""

import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack, nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rich.console import Console

from torrent_finder import acquisition, downloader, main, torrent_session
from torrent_finder.torrent_meta import TorrentFile, TorrentMetadata
from torrent_finder.torrent_session import TorrentSession
from isolation import isolate_store

MAGNET = "magnet:?xt=urn:btih:" + "a" * 40


class FakeProcess:
    """A child process that runs until it finishes or is killed."""

    pid = 4242

    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode


class PlayerOwnershipTests(unittest.TestCase):
    """A03: a stream controls only the VLC window it opened, and only while live."""

    def setUp(self):
        self.windows, self.killed = [], []

        def launch(url, sub_paths):
            self.windows.append(FakeProcess())
            return self.windows[-1]

        def kill(process):
            self.killed.append(process)
            process.returncode = 1

        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(downloader, "_launch_vlc", side_effect=launch))
        stack.enter_context(patch.object(downloader, "_kill_process_tree", side_effect=kill))
        stack.enter_context(patch.object(downloader, "_VLC_GRACE_S", 0))
        # platform.system() itself runs a subprocess the first time; resolve it first.
        stack.enter_context(patch.object(downloader.platform, "system", return_value=downloader.platform.system()))
        # Any global process lookup or termination (tasklist, taskkill /IM, pkill) runs here.
        self.global_commands = stack.enter_context(patch.object(downloader.subprocess, "run"))

    def test_v_reopens_only_when_its_own_window_was_closed(self):
        player = downloader._StreamPlayer("http://127.0.0.1:8080/x", None)
        self.assertTrue(player.launch())
        self.assertFalse(player.launch())  # already open: no duplicate
        self.windows[0].returncode = 0  # the user closed it
        self.assertTrue(player.launch())
        self.assertEqual(len(self.windows), 2)
        self.global_commands.assert_not_called()

    def test_ending_closes_its_own_windows_and_stops_later_launches(self):
        player = downloader._StreamPlayer("http://127.0.0.1:8080/x", None)
        player.launch()
        self.windows[0].returncode = 0  # the user closed it, then reopened with 'v'
        player.launch()
        player.end()
        self.assertEqual(self.killed, [self.windows[1]])  # already-closed windows are left alone
        self.assertFalse(player.launch())
        self.global_commands.assert_not_called()

    def test_ctrl_c_while_streaming_closes_this_streams_window(self):
        backend = FakeProcess()
        polls = iter([None, KeyboardInterrupt()])

        def interrupted_sleep(seconds):
            outcome = next(polls, None)
            if isinstance(outcome, BaseException):
                raise outcome

        with patch.object(downloader.subprocess, "Popen", return_value=backend), \
             patch.object(downloader, "_start_vlc_hotkey_thread", return_value=threading.Event()), \
             patch.object(downloader.time, "sleep", side_effect=interrupted_sleep):
            with patch.object(downloader._StreamPlayer, "launch_when_ready",
                              lambda player, host, port: player.launch()), \
                 self.assertRaises(KeyboardInterrupt):
                downloader._run_stream(["webtorrent"], "http://127.0.0.1:8080/x", allow_navigate=False,
                                       launch_vlc_when_ready=("127.0.0.1", 8080))
        self.assertEqual(self.killed, [backend, self.windows[0]])
        self.global_commands.assert_not_called()

    def test_nothing_launches_once_the_episode_ended(self):
        player = downloader._StreamPlayer("http://127.0.0.1:8080/x", None)
        player.end()  # e.g. 'v' or a waiter racing the end of the episode
        self.assertFalse(player.launch())
        self.assertEqual(self.windows, [])

    def test_a_waiter_that_wakes_after_the_episode_ended_never_launches(self):
        release = threading.Event()

        def port_opens_late(host, port, timeout, stop):
            release.wait(5)
            return True  # the server came up — but too late

        player = downloader._StreamPlayer("http://127.0.0.1:8080/x", None)
        with patch.object(downloader, "_wait_for_port", side_effect=port_opens_late):
            waiter = player.launch_when_ready("127.0.0.1", 8080)
            player.end()
            release.set()
            waiter.join(5)
        self.assertEqual(self.windows, [])

    def test_ending_during_the_grace_period_cancels_the_launch(self):
        player = downloader._StreamPlayer("http://127.0.0.1:8080/x", None)
        with patch.object(downloader, "_wait_for_port", return_value=True), \
             patch.object(downloader, "_VLC_GRACE_S", 30):
            waiter = player.launch_when_ready("127.0.0.1", 8080)
            player.end()
            waiter.join(5)
        self.assertFalse(waiter.is_alive())
        self.assertEqual(self.windows, [])

    def test_next_episode_closes_this_streams_window_and_backend(self):
        backend, hotkeys = FakeProcess(), {}

        def capture_hotkeys(player, advance_event, back_event):
            hotkeys.update(player=player, advance=advance_event)
            return threading.Event()

        def press_n_once_playing():
            deadline = time.monotonic() + 5
            while not self.windows and time.monotonic() < deadline:
                time.sleep(0.01)
            hotkeys["advance"].set()

        with patch.object(downloader.subprocess, "Popen", return_value=backend), \
             patch.object(downloader, "_start_vlc_hotkey_thread", side_effect=capture_hotkeys), \
             patch.object(downloader, "_wait_for_port", return_value=True):
            threading.Thread(target=press_n_once_playing, daemon=True).start()
            rc, nav = downloader._run_stream(["webtorrent"], "http://127.0.0.1:8080/x", allow_navigate=True,
                                             launch_vlc_when_ready=("127.0.0.1", 8080))
        self.assertEqual(nav, "next")
        self.assertEqual(self.killed, [backend, self.windows[0]])
        self.assertTrue(hotkeys["player"].ended.is_set())
        self.global_commands.assert_not_called()

    def test_windows_vlc_gets_its_own_instance(self):
        with patch.object(downloader, "_resolve_vlc_path", return_value="vlc.exe"), \
             patch.object(downloader.platform, "system", return_value="Windows"):
            command = downloader._build_vlc_cmd("http://127.0.0.1:8080/x", ["a.srt", "b.srt"])
        self.assertEqual(command, ["vlc.exe", "http://127.0.0.1:8080/x", "--no-one-instance",
                                   "--sub-file", "a.srt", "--input-slave", "b.srt"])


class StreamOutcomeTests(unittest.TestCase):
    """A07: failures are explained; navigation and cancel are not errors."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.log = os.path.join(directory.name, "stream.log")
        self.screen = Console(file=io.StringIO(), width=200, color_system=None)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(downloader, "console", self.screen))
        for name in ("_print_stream_header", "_clear_terminal", "_reset_terminal_title", "_reset_scroll_region"):
            stack.enter_context(patch.object(downloader, name))
        stack.enter_context(patch.object(downloader.time, "sleep"))
        stack.enter_context(patch.object(downloader.shutil, "which", return_value="backend"))
        stack.enter_context(patch.object(downloader, "_new_stream_log", return_value=self.log))
        stack.enter_context(patch.object(downloader, "is_quiet_mode", return_value=True))

    def session(self):
        files = [TorrentFile(1, "Show/Ep 01.mkv", 10), TorrentFile(2, "Show/Ep 02.mkv", 10)]
        return SimpleNamespace(magnet=MAGNET, selected_files=None, stream_indexes=[1, 2],
                               file_list=files, torrent_name="Show", sub_paths={})

    def stream(self, adapter, runs):
        with patch.object(downloader, "_run_stream", side_effect=runs) as run:
            return adapter(self.session()), run

    def test_outcomes_for_both_backends(self):
        for adapter in (downloader.stream_with_webtorrent, downloader.stream_with_peerflix):
            with self.subTest(adapter=adapter.__name__):
                with open(self.log, "w", encoding="utf-8") as log:
                    log.write("\x1b[31mError: listen EADDRINUSE: address already in use\x1b[0m\n")
                self.screen.file.truncate(0)
                outcome, run = self.stream(adapter, [(42, "none")])
                printed = self.screen.file.getvalue()
                self.assertEqual(outcome, "failed")
                self.assertIn("exit code 42", printed)
                self.assertIn("Error: listen EADDRINUSE", printed)
                self.assertIn(self.log, printed)
                self.assertEqual(run.call_args.kwargs["log_path"], self.log)

                self.screen.file.truncate(0)
                outcome, run = self.stream(adapter, [(1, "next"), (0, "none")])
                self.assertEqual((outcome, run.call_count), ("ended", 2))  # killed on 'n' is not an error
                self.assertNotIn("error", self.screen.file.getvalue().lower())

                self.screen.file.truncate(0)
                outcome, _ = self.stream(adapter, KeyboardInterrupt)
                self.assertEqual(outcome, "cancelled")
                self.assertNotIn("error", self.screen.file.getvalue().lower())

    def test_backend_error_output_reaches_the_log_even_in_quiet_mode(self):
        code = "import sys; sys.stderr.write('tracker exploded\\n'); sys.exit(3)"
        rc, nav = downloader._run_stream([sys.executable, "-c", code], None, allow_navigate=False,
                                         quiet=True, log_path=self.log)
        self.assertEqual((rc, nav), (3, "none"))
        self.assertIn("tracker exploded", downloader._log_tail(self.log))

    def test_long_logs_keep_only_their_newest_part(self):
        with open(self.log, "w", encoding="utf-8") as log:
            log.write("old\n" * 1000 + "newest line\n")
        downloader._trim_log(self.log, limit=100)
        self.assertLessEqual(os.path.getsize(self.log), 100)
        self.assertTrue(downloader._log_tail(self.log).endswith("newest line"))


NPM_SHIM = r'''@ECHO off
GOTO start
:find_dp0
SET dp0=%~dp0
EXIT /b
:start
SETLOCAL
CALL :find_dp0

IF EXIST "%dp0%\node.exe" (
  SET "_prog=%dp0%\node.exe"
) ELSE (
  SET "_prog=node"
  SET PATHEXT=%PATHEXT:;.JS;=;%
)

endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  "%dp0%\node_modules\fake-cli\cli.js" %*
'''


@unittest.skipUnless(os.name == "nt" and shutil.which("node"), "Windows npm wrappers need node")
class NodeCliLaunchTests(unittest.TestCase):
    """Magnets reach webtorrent / peerflix intact, never through cmd.exe."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = directory.name
        os.makedirs(os.path.join(self.root, "node_modules", "fake-cli"))
        with open(os.path.join(self.root, "node_modules", "fake-cli", "cli.js"), "w", encoding="utf-8") as script:
            script.write("console.log(JSON.stringify(process.argv.slice(2)))\n")
        self.screen = Console(file=io.StringIO(), width=200, color_system=None)
        self.real_which = shutil.which

    def command(self, wrapper):
        with patch.object(downloader.shutil, "which",
                          side_effect=lambda name: wrapper if name == "webtorrent" else self.real_which(name)), \
             patch.object(downloader, "console", self.screen):
            return downloader._cli_command("webtorrent")

    def write(self, name, text):
        path = os.path.join(self.root, name)
        with open(path, "w", encoding="utf-8") as wrapper:
            wrapper.write(text)
        return path

    def test_npm_and_yarn_wrappers_run_the_script_with_every_argument(self):
        npm = self.write("webtorrent.cmd", NPM_SHIM)
        yarn = self.write("yarn-webtorrent.cmd", '@"%~dp0\\webtorrent.cmd" %*\n')
        magnet = MAGNET + '&dn=x"&echo INJECTED&"&tr=udp://tracker.example:1337'
        args = ["download", magnet, "--port", "8080", "--select", "3"]
        for wrapper in (npm, yarn):
            with self.subTest(wrapper=os.path.basename(wrapper)):
                command = self.command(wrapper)
                self.assertTrue(command[-1].endswith("cli.js"))
                out = subprocess.run([*command, *args], capture_output=True, text=True, timeout=60)
                self.assertEqual(json.loads(out.stdout), args)

    def test_unrecognised_wrapper_is_refused_instead_of_run_through_cmd(self):
        self.assertIsNone(self.command(self.write("webtorrent.cmd", "@echo %*\n")))
        self.assertIn("isn't a recognised npm launcher", self.screen.file.getvalue())


class MagnetNameTests(unittest.TestCase):
    def test_names_with_magnet_syntax_stay_one_parameter(self):
        from urllib.parse import parse_qs, urlsplit
        from torrent_finder.utils import build_magnet
        name = "Tom & Jerry + [1080p] #1 100%"
        magnet = build_magnet("a" * 40, name)
        params = parse_qs(urlsplit(magnet).query)
        self.assertEqual(params["dn"], [name])
        self.assertEqual(set(params), {"xt", "dn", "tr"})
        self.assertEqual(downloader._magnet_dn(magnet), name)


class DownloadCancelTests(unittest.TestCase):
    """Ctrl+C stops a terminal download within a moment, not when it finishes."""

    def test_ctrl_c_cancels_a_running_download(self):
        child = [sys.executable, "-c", "import time; time.sleep(20)"]
        threading.Timer(0.5, signal.raise_signal, (signal.SIGINT,)).start()
        started = time.monotonic()
        with patch.object(downloader, "console", Console(file=io.StringIO())):
            self.assertIsNone(downloader._run_download(child, quiet=False, status_msg="x"))
        self.assertLess(time.monotonic() - started, 8)


class StreamPreparationTests(unittest.TestCase):
    """A08: cancelling the file-list fetch for a stream starts nothing."""

    def setUp(self):
        isolate_store(self)
        self.provider = SimpleNamespace(slug="movies", result_sort="relevance", filter_summary=lambda: "No presets",
                                        supports_subtitles=True, supports_episode_picker=True,
                                        supports_streaming=True)
        self.result = {"name": "Example", "info_hash": "a" * 40, "seeders": 1, "source": "Apibay"}

    def run_stream_choice(self, session):
        adapter = Mock()
        adapter.pick.return_value = acquisition.PickOutcome("menu", MAGNET)
        with patch.object(main, "interactive_select", side_effect=[("one", 0), None]), \
             patch.object(main.acquisition, "for_result", return_value=adapter), \
             patch.object(main, "TorrentSession", return_value=session), \
             patch.object(main, "download_method_prompt", side_effect=["stream_w", "back"]) as menu, \
             patch.object(main, "has_aria2", return_value=True), \
             patch.object(main, "start_esc_listener", return_value=Mock()), \
             patch.object(main.console, "status", return_value=nullcontext()), \
             patch.object(main.console, "print"), \
             patch.object(main.readchar, "readkey"), \
             patch.object(main, "clear_screen"), \
             patch.object(main, "record_torrent_picked"), patch.object(main, "record_method_pick"), \
             patch.object(main, "stream_with_webtorrent", return_value="ended") as stream:
            self.assertEqual(main.browse_results(self.provider, [self.result]), "back")
        self.assertEqual(menu.call_count, 2)  # back at the same download options
        self.assertEqual([call.kwargs["focus"] for call in menu.call_args_list], [None, "stream_w"])
        return stream

    def session(self, fetch, status="unknown"):
        return SimpleNamespace(magnet=MAGNET, result=self.result, selected_files=None, sub_choice=None,
                               files_meta_status=status, fetch_files_meta=Mock(side_effect=fetch))

    def test_ctrl_c_or_esc_during_preparation_starts_no_stream(self):
        def esc(cancel_event):
            cancel_event.set()
        for name, fetch in (("ctrl+c", KeyboardInterrupt), ("esc", esc)):
            with self.subTest(name):
                self.run_stream_choice(self.session(fetch)).assert_not_called()

    def test_unavailable_file_list_still_offers_default_playback(self):
        session = self.session(lambda cancel_event: None)
        self.run_stream_choice(session).assert_called_once_with(session)
        failed_before = self.session(AssertionError("must not fetch again"), status="unavailable")
        self.run_stream_choice(failed_before).assert_called_once_with(failed_before)


class MethodFocusTests(unittest.TestCase):
    def start_row(self, **kwargs):
        from torrent_finder.ui import prompts
        with patch.object(prompts, "arrow_select", return_value=None) as select,              patch.object(prompts, "has_webtorrent", return_value=True),              patch.object(prompts, "has_peerflix", return_value=True),              patch.object(prompts, "has_aria2", return_value=True):
            prompts.download_method_prompt(magnet=MAGNET, **kwargs)
        items = select.call_args.args[0]
        return items[select.call_args.kwargs["start_index"]].value

    def test_returning_keeps_the_last_option_and_a_new_torrent_starts_on_the_client(self):
        self.assertEqual(self.start_row(), "t")
        self.assertEqual(self.start_row(focus="stream_w"), "stream_w")
        self.assertEqual(self.start_row(focus="pick_episodes", show_episode_picker=True), "pick_episodes")
        self.assertEqual(self.start_row(focus="no-longer-offered"), "t")


class MetadataRetryTests(unittest.TestCase):
    """A09: a failed fetch can be retried; a successful one is kept."""

    def test_timeout_then_retry_succeeds_and_success_is_reused(self):
        found = TorrentMetadata("Show", [TorrentFile(1, "Show/Ep 01.mkv", 10)])
        session = TorrentSession({"name": "Show"}, MAGNET)
        with patch.object(torrent_session, "fetch_file_list", side_effect=[None, found]) as fetch:
            self.assertEqual(session.file_list, [])  # reading never fetches by itself
            fetch.assert_not_called()
            self.assertIsNone(session.fetch_files_meta())
            self.assertEqual(session.files_meta_status, "unavailable")
            self.assertIs(session.fetch_files_meta(), found)
            self.assertIs(session.fetch_files_meta(), found)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual((session.files_meta_status, session.torrent_name), ("ok", "Show"))

    def test_cancelled_fetch_changes_nothing(self):
        session = TorrentSession({"name": "Show"}, MAGNET)
        cancel = threading.Event()

        def cancelled(magnet, cancel_event):
            cancel_event.set()

        with patch.object(torrent_session, "fetch_file_list", side_effect=cancelled):
            self.assertIsNone(session.fetch_files_meta(cancel_event=cancel))
        self.assertEqual(session.files_meta_status, "unknown")


if __name__ == "__main__":
    unittest.main()
