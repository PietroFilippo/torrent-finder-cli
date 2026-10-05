"""In-place updates (ADR-0024): installer output, hidden installers, launchers and restarting."""

import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from torrent_finder import updates
from torrent_finder.state import load_setting, save_setting

PIP_OUTPUT = """\
Requirement already satisfied: torrent-finder-cli in c:\\venv\\lib\\site-packages (0.9.0)
Collecting torrent-finder-cli
  Downloading torrent_finder_cli-0.9.1-py3-none-any.whl.metadata (84 kB)
Requirement already satisfied: rich in c:\\venv\\lib\\site-packages (from torrent-finder-cli) (14.0.0)
Downloading torrent_finder_cli-0.9.1-py3-none-any.whl (719 kB)
Progress 0 of 719511
Progress 262144 of 719511
Progress 719511 of 719511
Installing collected packages: torrent-finder-cli
  Attempting uninstall: torrent-finder-cli
    Found existing installation: torrent-finder-cli 0.9.0
    Uninstalling torrent-finder-cli-0.9.0:
      Successfully uninstalled torrent-finder-cli-0.9.0
Successfully installed torrent-finder-cli-0.9.1
"""
PIP_CURRENT = "Requirement already satisfied: torrent-finder-cli in c:\\venv\\lib\\site-packages (0.9.1)\n"
PIP_FAILED = "Collecting torrent-finder-cli\nERROR: Could not find a version that satisfies the requirement torrent-finder-cli\n"
PIPX_UPGRADED = "upgraded package torrent-finder-cli from 0.9.0 to 0.9.1 (location: C:\\pipx\\venvs\\torrent-finder-cli)\n"
PIPX_CURRENT = "torrent-finder-cli is already at latest version 0.9.1 (location: C:\\pipx\\venvs\\torrent-finder-cli)\n"


class InstallerOutputTests(unittest.TestCase):
    def feed(self, text):
        calls = []
        output = updates._InstallerOutput(lambda stage, detail="", **extra: calls.append((stage, detail, extra)))
        for line in text.splitlines():
            output.feed(line)
        return output, calls

    def test_pip_output_becomes_stages_and_download_bytes(self):
        output, calls = self.feed(PIP_OUTPUT)
        wheel = "torrent_finder_cli-0.9.1-py3-none-any.whl"
        self.assertEqual(calls, [
            ("downloading", wheel, {}),
            ("downloading", wheel, {"done": 0, "total": 719511}),
            ("downloading", wheel, {"done": 262144, "total": 719511}),
            ("downloading", wheel, {"done": 719511, "total": 719511}),
            ("installing", "Installing torrent-finder-cli.", {}),
            ("installing", "Installed torrent-finder-cli 0.9.1.", {"latest": "0.9.1"}),
        ])
        self.assertEqual((output.version, output.current, output.error), ("0.9.1", False, ""))

    def test_nothing_newer_and_errors_are_recognised(self):
        self.assertTrue(self.feed(PIP_CURRENT)[0].current)
        self.assertTrue(self.feed(PIPX_CURRENT)[0].current)
        self.assertIn("Could not find a version", self.feed(PIP_FAILED)[0].error)
        self.assertEqual(self.feed(PIPX_UPGRADED)[0].version, "0.9.1")

    def test_pipx_listing_the_version_pip_just_installed_is_not_nothing_new(self):
        output, _calls = self.feed(PIP_OUTPUT + PIPX_CURRENT)
        self.assertFalse(output.current)

    def test_unknown_download_size_is_not_a_percentage(self):
        _output, calls = self.feed("Downloading x.whl\nProgress 4096 of 0\n")
        self.assertEqual(calls[-1], ("downloading", "x.whl", {"done": 4096, "total": None}))

    def test_pip_updates_pipx_installs_only_when_pipx_tracks_pypi(self):
        cases = [("torrent-finder-cli", True), ("torrent_finder_cli==0.8.1", True), ("Torrent-Finder-CLI[extra]>=0.8", True),
                 ("C:\\wheels\\torrent_finder_cli-0.8.1-py3-none-any.whl", False),
                 ("git+https://github.com/PietroFilippo/torrent-finder-cli", False)]
        with tempfile.TemporaryDirectory() as directory:
            for source, expected in cases:
                with self.subTest(source=source):
                    Path(directory, "pipx_metadata.json").write_text(
                        json.dumps({"main_package": {"package_or_url": source}}), encoding="utf-8")
                    with patch.object(updates.sys, "prefix", directory):
                        self.assertEqual(updates._pipx_tracks_index(), expected)
            with patch.object(updates.sys, "prefix", str(Path(directory, "missing"))):
                self.assertTrue(updates._pipx_tracks_index())

    def test_raw_progress_only_with_a_pip_that_has_it(self):
        import importlib.metadata as md
        for version, mode in [("25.1.1", "raw"), ("24.1", "raw"), ("24.0", "off"), ("9.0.1", "off")]:
            with self.subTest(version=version), patch.object(md, "version", return_value=version):
                command = updates._pip_command()
            self.assertEqual(command[command.index("--progress-bar") + 1], mode)
            self.assertEqual(command[:3], [sys.executable, "-m", "pip"])
        with patch.object(md, "version", side_effect=md.PackageNotFoundError("pip")):
            self.assertIsNone(updates._pip_command())


class PackageUpdateTests(unittest.TestCase):
    """run_update for pip/pipx installs, with the installer commands simulated."""

    def update(self, outputs, *, pip=True, pipx=True, stream_error=None, interrupt=False, installed=()):
        calls, progress, interrupted = [], [], []

        def stream(command, log, on_line):
            name = "pipx" if command[0] == "pipx" else "pip"
            calls.append(name)
            if interrupt:
                signal.getsignal(signal.SIGINT)(signal.SIGINT, None)  # what Ctrl+C runs
            if stream_error:
                raise stream_error
            text, code = outputs[name]
            for line in text.splitlines():
                on_line(line)
            return code

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(updates, "_update_files", return_value=(Path(directory, "status.json"), Path(directory, "update.log"))), \
             patch.object(updates, "_pipx_install", return_value=pipx), \
             patch.object(updates, "_pip_command", return_value=["python", "-m", "pip", "install"] if pip else None), \
             patch.object(updates, "_installed_files", return_value=list(installed)), \
             patch.object(updates, "_move_running_launchers", return_value=["moved"]), \
             patch.object(updates, "_settle_launchers") as settle, \
             patch.object(updates, "_stream", side_effect=stream):
            try:
                result = updates.run_update({"kind": "pip", "current": "0.9.0", "latest": "0.9.1"},
                                            on_progress=lambda *args, **extra: progress.append((args, extra)),
                                            on_interrupt=lambda: interrupted.append(True))
            except Exception as error:  # noqa: BLE001  # settle must run even then
                result = error
        settle.assert_called_once_with(["moved"])
        return result, calls, progress, interrupted

    def test_pip_installs_with_progress_then_pipx_refreshes_its_records(self):
        result, calls, progress, _ = self.update({"pip": (PIP_OUTPUT, 0), "pipx": (PIPX_UPGRADED, 0)})
        self.assertEqual(result, updates.UpdateResult(True, "Torrent Finder 0.9.1 is installed.", restart=True))
        self.assertEqual(calls, ["pip", "pipx"])
        stages = [args[0] for args, _extra in progress]
        self.assertEqual(stages[0], "preparing")
        self.assertIn("finishing", stages)
        self.assertIn({"done": 262144, "total": 719511}, [extra for _args, extra in progress])

    def test_pip_failure_stops_before_pipx_and_says_where_to_look(self):
        result, calls, _progress, _ = self.update({"pip": (PIP_FAILED, 1)})
        self.assertFalse(result.ok)
        self.assertFalse(result.restart)
        self.assertEqual(calls, ["pip"])
        self.assertIn("Could not find a version", result.message)
        self.assertIn("update.log", result.message)
        self.assertIn("pipx upgrade torrent-finder-cli", result.message)

    def test_pipx_bookkeeping_failure_after_pip_installed_is_still_an_update(self):
        result, _calls, _progress, _ = self.update({"pip": (PIP_OUTPUT, 0), "pipx": ("", 1)})
        self.assertTrue(result.ok and result.restart)
        self.assertIn("pipx could not refresh its records", result.message)

    def test_failed_pipx_upgrade_is_never_reported_as_success(self):
        # Without pip, pipx does the whole update; a nonzero exit (e.g. a
        # launcher it could not replace) is a failure, whatever metadata says.
        result, calls, _progress, _ = self.update({"pipx": (PIPX_UPGRADED, 1)}, pip=False)
        self.assertFalse(result.ok)
        self.assertEqual(calls, ["pipx"])
        self.assertIn("pipx upgrade torrent-finder-cli", result.message)

    def test_pipx_alone_can_update(self):
        result, _calls, _progress, _ = self.update({"pipx": (PIPX_UPGRADED, 0)}, pip=False)
        self.assertEqual(result, updates.UpdateResult(True, "Torrent Finder 0.9.1 is installed.", restart=True))

    def test_nothing_newer_needs_no_restart_or_pipx(self):
        result, calls, _progress, _ = self.update({"pip": (PIP_CURRENT, 0)})
        self.assertEqual(result, updates.UpdateResult(True, "Torrent Finder is already up to date."))
        self.assertEqual(calls, ["pip"])

    def test_plain_pip_install_has_no_pipx_step(self):
        result, calls, _progress, _ = self.update({"pip": (PIP_OUTPUT, 0)}, pipx=False)
        self.assertTrue(result.restart)
        self.assertEqual(calls, ["pip"])

    def test_launchers_are_settled_even_when_the_installer_breaks(self):
        result, _calls, _progress, _ = self.update({}, stream_error=RuntimeError("boom"))
        self.assertIsInstance(result, RuntimeError)

    def test_ctrl_c_while_installing_only_explains(self):
        before = signal.getsignal(signal.SIGINT)
        result, _calls, _progress, interrupted = self.update({"pip": (PIP_OUTPUT, 0), "pipx": ("", 0)}, interrupt=True)
        self.assertTrue(result.ok)
        self.assertEqual(interrupted, [True, True])
        self.assertIs(signal.getsignal(signal.SIGINT), before)

    def test_a_file_held_open_stops_the_update_before_pip_runs(self):
        # pip does not put back what it moved when a later move fails: the app would be gone.
        busy = Path("C:/venv/Scripts/torrent.exe")
        with patch.object(updates, "_held_open", side_effect=lambda path: path == busy):
            result, calls, _progress, _ = self.update({}, installed=[Path("C:/venv/a.py"), busy])
        self.assertFalse(result.ok)
        self.assertIn("torrent.exe", result.message)
        self.assertIn("Nothing was changed", result.message)
        self.assertEqual(calls, [])

    def test_metadata_is_read_before_the_launcher_is_let_go(self):
        order = []
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(updates, "_update_files", return_value=(Path(directory, "status.json"), Path(directory, "update.log"))), \
             patch.object(updates, "_pipx_install", return_value=False), \
             patch.object(updates, "_pip_command", side_effect=lambda: order.append("pip version") or ["pip"]), \
             patch.object(updates, "_installed_files", side_effect=lambda: order.append("files") or []), \
             patch.object(updates, "_launcher_names", side_effect=lambda: order.append("names") or ["torrent"]), \
             patch.object(updates, "_move_running_launchers", side_effect=lambda names: order.append("move") or []), \
             patch.object(updates, "_stream", side_effect=lambda *args: order.append("pip") or 0):
            updates.run_update({"kind": "pip"})
        self.assertEqual(order[-2:], ["move", "pip"])
        self.assertEqual(sorted(order[:-2]), ["files", "names", "pip version"])

    def test_without_pip_or_pipx_nothing_runs(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(updates, "_update_files", return_value=(Path(directory, "status.json"), Path(directory, "update.log"))), \
             patch.object(updates, "_pipx_install", return_value=False), \
             patch.object(updates, "_pip_command", return_value=None), \
             patch.object(updates, "_stream") as stream, \
             patch.object(updates, "_move_running_launchers") as move:
            result = updates.run_update({"kind": "pip"})
        self.assertFalse(result.ok)
        self.assertIn("pip is not available", result.message)
        stream.assert_not_called()
        move.assert_not_called()

    def test_failed_browser_launch_does_not_claim_it_opened(self):
        with patch("webbrowser.open", return_value=False):
            self.assertFalse(updates.run_update({"kind": "binary"}).ok)


class CheckoutUpdateTests(unittest.TestCase):
    def update(self, text, code):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(updates, "_update_files", return_value=(Path(directory, "status.json"), Path(directory, "update.log"))), \
             patch.object(updates, "_stream", side_effect=lambda command, log, on_line: [on_line(line) for line in text.splitlines()] and code):
            return updates.run_update({"kind": "git", "behind": 2})

    def test_pulled_changes_restart_the_app(self):
        self.assertEqual(self.update("Updating 1a2b..3c4d\nFast-forward\n", 0),
                         updates.UpdateResult(True, "Downloaded the latest source changes.", restart=True))

    def test_nothing_to_pull_and_failures_do_not_restart(self):
        self.assertFalse(self.update("Already up to date.\n", 0).restart)
        failed = self.update("fatal: Not possible to fast-forward, aborting.\n", 1)
        self.assertFalse(failed.ok)
        self.assertIn("git pull failed", failed.message)


class HiddenInstallerTests(unittest.TestCase):
    def test_installer_output_is_logged_and_passed_on_line_by_line(self):
        script = "import sys; print('Collecting torrent-finder-cli'); print('Progress 5 of 10'); sys.stdout.write('a\\rb\\n'); sys.exit(3)"
        lines, log = [], io.StringIO()
        code = updates._stream([sys.executable, "-c", script], log, lines.append)
        self.assertEqual(code, 3)
        self.assertEqual(lines, ["Collecting torrent-finder-cli", "Progress 5 of 10", "a", "b"])
        self.assertIn("$ ", log.getvalue())
        self.assertIn("Progress 5 of 10", log.getvalue())
        self.assertIn("(exit code 3)", log.getvalue())

    def test_installer_cannot_open_a_window_or_receive_the_apps_ctrl_c(self):
        with patch.object(updates.subprocess, "Popen", side_effect=OSError("stop")) as popen:
            updates._stream(["fixture"], io.StringIO(), lambda line: None)
        options = popen.call_args.kwargs
        if sys.platform == "win32":
            self.assertEqual(options["creationflags"], subprocess.CREATE_NO_WINDOW)
        else:
            self.assertTrue(options["start_new_session"])
        self.assertEqual(options["stdin"], subprocess.DEVNULL)

    @unittest.skipUnless(sys.platform == "win32", "Windows consoles")
    def test_a_real_installer_process_has_no_console_window(self):
        # The old updater's installer got a console of its own: the blank tab.
        lines = []
        updates._stream([sys.executable, "-c", "import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())"],
                        io.StringIO(), lines.append)
        self.assertEqual(lines, ["0"])

    def test_a_missing_installer_is_reported(self):
        lines = []
        code = updates._stream(["torrent-finder-no-such-installer"], io.StringIO(), lines.append)
        self.assertNotEqual(code, 0)
        self.assertTrue(lines and lines[0].startswith("ERROR: could not start"))

    def test_installer_that_never_finishes_is_stopped(self):
        lines = []
        with patch.object(updates, "_STEP_TIMEOUT", 0.2):
            code = updates._stream([sys.executable, "-c", "import time; time.sleep(30)"], io.StringIO(), lines.append)
        self.assertNotEqual(code, 0)
        self.assertIn("without finishing", lines[-1])


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        save_setting(updates._MOVED_KEY, [])

    def test_candidates_cover_the_environment_pipx_and_path_launchers(self):
        venv, pipx_bin, elsewhere = self.folder / "venv" / "Scripts", self.folder / "bin", self.folder / "other"
        expected = [venv / "torrent-finder.exe", venv / "torrent.exe", pipx_bin / "torrent-finder.exe", elsewhere / "torrent.exe"]
        for path in [*expected, venv / "python.exe", self.folder / "unrelated.exe"]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"MZ")
        with patch.object(updates.sys, "executable", str(venv / "python.exe")), \
             patch.dict(os.environ, {"PIPX_BIN_DIR": str(pipx_bin)}), \
             patch.object(updates.shutil, "which", side_effect=lambda name: str(elsewhere / "torrent.exe") if name == "torrent" else None), \
             patch.object(updates.sysconfig, "get_path", side_effect=KeyError("scripts")):
            self.assertEqual(sorted(updates._launcher_candidates(["torrent-finder", "torrent"])), sorted(expected))

    def test_only_windows_moves_launchers(self):
        with patch.object(updates.os, "name", "posix"), \
             patch.object(updates, "_launcher_candidates") as candidates:
            self.assertEqual(updates._move_running_launchers(["torrent"]), [])
        candidates.assert_not_called()

    def test_launchers_the_installer_did_not_replace_are_put_back(self):
        original, aside = self.folder / "torrent.exe", self.folder / "torrent.exe.1a2b3c4d.old"
        aside.write_bytes(b"old")
        updates._settle_launchers([(original, aside)])
        self.assertEqual(original.read_bytes(), b"old")
        self.assertFalse(aside.exists())

    def test_replaced_launchers_that_nothing_runs_are_deleted(self):
        original, aside = self.folder / "torrent.exe", self.folder / "torrent.exe.1a2b3c4d.old"
        original.write_bytes(b"new")
        aside.write_bytes(b"old")
        updates._settle_launchers([(original, aside)])
        self.assertEqual(original.read_bytes(), b"new")
        self.assertFalse(aside.exists())
        self.assertEqual(load_setting(updates._MOVED_KEY), [])

    def test_startup_cleanup_only_deletes_files_it_named(self):
        ours, unrelated = self.folder / "torrent.exe.1a2b3c4d.old", self.folder / "important.exe"
        ours.write_bytes(b"old")
        unrelated.write_bytes(b"keep")
        save_setting(updates._MOVED_KEY, [str(ours), str(unrelated), 7])
        updates.remove_moved_launchers()
        self.assertFalse(ours.exists())
        self.assertTrue(unrelated.exists())
        self.assertEqual(load_setting(updates._MOVED_KEY), [])

    @unittest.skipUnless(sys.platform == "win32", "Windows file locking")
    def test_running_launcher_is_moved_aside_then_deleted_after_it_exits(self):
        running, idle = self.folder / "torrent-finder.exe", self.folder / "torrent.exe"
        for path in (running, idle):
            shutil.copy(Path(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "ping.exe"), path)
        process = subprocess.Popen([str(running), "-n", "30", "127.0.0.1"], stdout=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            with patch.object(updates, "_launcher_candidates", return_value=[running, idle]):
                moved = updates._move_running_launchers(["torrent-finder", "torrent"])
            self.assertEqual([original for original, _aside in moved], [running])
            self.assertTrue(idle.exists())
            running.write_bytes(b"new launcher")  # what pip or pipx writes next
            updates._settle_launchers(moved)
            aside = moved[0][1]
            self.assertTrue(aside.exists())  # still running
            self.assertEqual(load_setting(updates._MOVED_KEY), [str(aside)])
        finally:
            process.kill()
            process.wait()
        updates.remove_moved_launchers()
        self.assertFalse(aside.exists())
        self.assertEqual(load_setting(updates._MOVED_KEY), [])


@unittest.skipUnless(sys.platform == "win32", "Windows file sharing")
class HeldOpenTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_files_opened_without_rename_sharing_are_held_open(self):
        path = self.folder / "torrent_finder.py"
        path.write_text("x = 1")
        with open(path, "rb"):  # Python opens files without letting them be renamed
            self.assertTrue(updates._held_open(path))
        self.assertFalse(updates._held_open(path))
        self.assertFalse(updates._held_open(self.folder / "missing.py"))

    def test_a_running_program_alone_does_not_hold_its_file(self):
        program = self.folder / "torrent.exe"
        shutil.copy(Path(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "ping.exe"), program)
        process = subprocess.Popen([str(program), "-n", "30", "127.0.0.1"], stdout=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            self.assertFalse(updates._held_open(program))
        finally:
            process.kill()
            process.wait()

    def test_letting_go_of_the_launcher_allows_moving_it(self):
        # A console script runs with its launcher, a zip, first on sys.path;
        # metadata lookups then keep it open until their cache is cleared.
        import importlib.metadata as md
        import zipfile
        launcher = self.folder / "torrent-finder.exe"
        with zipfile.ZipFile(launcher, "w") as archive:
            archive.writestr("__main__.py", "")
        sys.path.insert(0, str(launcher))
        try:
            md.distributions()  # warm the cache with the zip in it
            list(md.distributions())
            self.assertTrue(updates._held_open(launcher))
            updates._release_launcher()
            self.assertFalse(updates._held_open(launcher))
        finally:
            sys.path.remove(str(launcher))
            updates._release_launcher()


class RelaunchTests(unittest.TestCase):
    def test_restart_uses_the_command_that_started_the_app(self):
        with tempfile.TemporaryDirectory() as directory:
            launcher = Path(directory, "torrent-finder.exe" if sys.platform == "win32" else "torrent-finder")
            launcher.write_bytes(b"")
            started = str(launcher)[:-len(".exe")] if sys.platform == "win32" else str(launcher)  # wrappers drop .exe
            with patch.object(updates.sys, "argv", [started, "-y"]):
                self.assertEqual(updates._restart_command(["-y"]), [str(launcher), "-y"])
        with patch.object(updates.sys, "argv", [str(Path(updates._REPO_DIR, "__main__.py"))]):
            self.assertEqual(updates._restart_command([]), [sys.executable, "-m", "torrent_finder"])

    def test_windows_waits_for_the_new_app_and_leaves_ctrl_c_to_it(self):
        before = signal.getsignal(signal.SIGINT)
        seen = []

        def call(command):
            handler = signal.getsignal(signal.SIGINT)
            handler(signal.SIGINT, None)  # must not raise in this process
            seen.append(command)
            return 4

        with patch.object(updates.os, "name", "nt"), patch.object(updates.subprocess, "call", side_effect=call), \
             patch.object(updates, "_restart_command", return_value=["torrent-finder"]):
            self.assertEqual(updates.relaunch([]), 4)
        self.assertEqual(seen, [["torrent-finder"]])
        self.assertIs(signal.getsignal(signal.SIGINT), before)

    def test_posix_replaces_the_process(self):
        class Replaced(Exception):
            pass
        with patch.object(updates.os, "name", "posix"), \
             patch.object(updates.os, "execv", side_effect=Replaced) as execv, \
             patch.object(updates, "_restart_command", return_value=["/usr/bin/torrent-finder", "-y"]):
            with self.assertRaises(Replaced):
                updates.relaunch(["-y"])
        execv.assert_called_once_with("/usr/bin/torrent-finder", ["/usr/bin/torrent-finder", "-y"])


class OlderVersionReportTests(unittest.TestCase):
    """Versions before in-place updates leave a report for the next launch."""

    def setUp(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, True)
        self.status, self.log = directory / "status.json", directory / "update.log"
        patcher = patch.object(updates, "_update_files", return_value=(self.status, self.log))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_finished_reports_are_shown_once(self):
        for state, expected in [("succeeded", "successfully"), ("failed", "did not complete")]:
            with self.subTest(state=state):
                self.status.write_text(f'{{"state": "{state}"}}')
                self.assertIn(expected, updates.consume_update_report())
                self.assertEqual(updates.consume_update_report(), "")

    def test_malformed_or_stale_status_does_not_claim_success(self):
        self.status.write_text("[]")
        self.assertEqual(updates.consume_update_report(), "")
        self.status.write_text('{"state":"pending","started_at":1}')
        self.assertIn("did not complete", updates.consume_update_report())

    def test_countdown_report_is_left_for_the_old_helper_until_it_expires(self):
        self.status.write_text('{"state":"succeeded", "reopen":"waiting", "reopen_at":103}')
        with patch.object(updates.time, "time", return_value=100):
            self.assertEqual(updates.consume_update_report(), "")
            self.assertTrue(self.status.exists())
        with patch.object(updates.time, "time", return_value=114):
            self.assertIn("successfully", updates.consume_update_report())


if __name__ == "__main__":
    unittest.main()
