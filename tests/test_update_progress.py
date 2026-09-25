import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from rich.console import Console

from torrent_finder import main as app, updates, update_worker
from torrent_finder.ui import update_progress as ui


class UpdateProgressTests(unittest.TestCase):
    def test_preview_cli_skips_normal_startup_and_persistence(self):
        for arguments, outcome in [(["--preview-update"], "success"), (["--preview-update", "failure"], "failure")]:
            with self.subTest(outcome=outcome), \
                 patch("sys.argv", ["torrent-finder", *arguments]), \
                 patch.object(app, "preview_update") as preview, \
                 patch.object(app, "_main_loop") as loop, \
                 patch.object(app, "record_session_start") as stats, \
                 patch.object(app, "add_runtime_seconds") as runtime:
                app.main()
            preview.assert_called_once_with(outcome)
            loop.assert_not_called()
            stats.assert_not_called()
            runtime.assert_not_called()

    def test_preview_runs_real_display_without_an_installer_or_job(self):
        for outcome in ("success", "failure"):
            output = io.StringIO()
            with patch.object(ui.time, "sleep"), \
                 patch.object(updates, "run_update") as update, \
                 patch.object(updates, "_update_files") as files, \
                 patch.object(updates.subprocess, "Popen") as popen:
                ui.preview_update(outcome, console=Console(file=output, width=48), pause=False)
            self.assertIn("PREVIEW", output.getvalue())
            self.assertIn("Update complete" if outcome == "success" else "Update did not complete", output.getvalue())
            update.assert_not_called()
            files.assert_not_called()
            popen.assert_not_called()

    def test_ctrl_c_in_preview_exits_without_a_traceback(self):
        with patch("sys.argv", ["torrent-finder", "--preview-update"]), \
             patch.object(app, "preview_update", side_effect=KeyboardInterrupt), \
             patch.object(app, "record_session_start") as stats:
            app.main()
        stats.assert_not_called()

    def test_panels_fit_small_terminals_and_animation_moves_without_percentages(self):
        for width in (32, 48, 80):
            output = io.StringIO()
            console = Console(file=output, width=width)
            for time in (0, 1, 2, 7):
                console.print(ui.update_panel(ui.preview_view(time), time, width=min(72, width)))
            self.assertTrue(all(len(line) <= width for line in output.getvalue().splitlines()))
            self.assertNotIn("%", output.getvalue())
            self.assertIn("Elapsed 00:07", output.getvalue())
        frames = []
        for elapsed in (2, 2.5):
            console = Console(file=io.StringIO(), width=72, record=True, color_system="truecolor")
            console.print(ui.update_panel(ui.preview_view(elapsed), elapsed))
            frames.append(console.export_html(inline_styles=True))
        self.assertNotEqual(*frames)

    def test_worker_publishes_installing_phase_then_real_outcome_for_same_job(self):
        for code in (0, 1):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                status, log = Path(directory)/"status.json", Path(directory)/"update.log"
                update_worker.write_status(status, state="pending", phase="waiting", job_id="job", current="1", latest="2", started_at=123)
                phases = []
                def run(*args, **kwargs):
                    phases.append(json.loads(status.read_text())["phase"])
                    return Mock(returncode=code)
                with patch.object(update_worker, "_wait_for_parent", return_value=True), \
                     patch.object(update_worker.time, "sleep"), \
                     patch.object(update_worker.subprocess, "run", side_effect=run):
                    update_worker.run_job(123, ["fixture"], status, log)
                data = ui.read_job(status, "job")
                self.assertEqual(phases, ["installing"])
                self.assertEqual(data["state"], "failed" if code else "succeeded")
                self.assertEqual(data["latest"], "2")
                self.assertEqual(data["started_at"], 123)

    def test_viewer_reads_archived_job_and_does_not_modify_it(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory)/"status.json"
            archive = status.with_name("last-update-status.json")
            status.write_text('{"job_id":"newer", "state":"pending"}')
            archive.write_text('{"job_id":"wanted", "state":"failed", "log":"fixture.log"}')
            before = archive.read_bytes(), status.read_bytes()
            output = io.StringIO()
            ui.watch_update(status, "wanted", console=Console(file=output, width=72), pause=False)
            self.assertIn("Update did not complete", output.getvalue())
            self.assertIn("fixture.log", output.getvalue())
            self.assertEqual(before, (archive.read_bytes(), status.read_bytes()))
            self.assertIsNone(ui.read_job(status, "unrelated"))

    def test_viewer_launch_failure_keeps_single_hidden_update_queued(self):
        with tempfile.TemporaryDirectory() as directory:
            status, log = Path(directory)/"status.json", Path(directory)/"update.log"
            with patch.object(updates, "_update_files", return_value=(status, log)), \
                 patch.object(updates.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True), \
                 patch.object(updates.subprocess, "DETACHED_PROCESS", 8, create=True), \
                 patch.object(updates.subprocess, "CREATE_NEW_CONSOLE", 16, create=True), \
                 patch.object(updates.subprocess, "Popen", side_effect=[Mock(), OSError("no console")]) as popen:
                ok, message = updates._schedule_update(["fixture"], show_progress=True)
                self.assertTrue(ok)
                self.assertIn("queued", message)
                self.assertEqual(popen.call_count, 2)
                worker, viewer = popen.call_args_list
                self.assertIn("torrent_finder.update_worker", worker.args[0])
                self.assertIn("--reopen", worker.args[0])
                self.assertIn("torrent_finder.ui.update_progress", viewer.args[0])
                self.assertNotEqual(worker.kwargs["creationflags"], viewer.kwargs["creationflags"])
                self.assertEqual(json.loads(status.read_text())["state"], "pending")
                updates._schedule_update(["fixture"], show_progress=True)
                self.assertEqual(popen.call_count, 2)  # no duplicate installer

    def test_inline_update_logs_output_and_reports_installing_phase(self):
        with tempfile.TemporaryDirectory() as directory:
            status, log = Path(directory)/"status.json", Path(directory)/"update.log"
            def run(*args, **kwargs):
                kwargs["stdout"].write("installer details")
                return Mock(returncode=0)
            progress = Mock()
            with patch.object(updates, "_update_files", return_value=(status, log)), \
                 patch.object(updates.subprocess, "run", side_effect=run):
                ok, message = updates.run_update({"kind": "git"}, on_progress=progress)
            self.assertTrue(ok, message)
            self.assertEqual(progress.call_args.args[0], "installing")
            self.assertEqual(log.read_text(), "installer details")

    def test_queue_is_never_displayed_as_already_installed(self):
        with patch.object(app, "run_update", return_value=(True, "queued")), \
             patch.object(app, "needs_exit_before_update", return_value=True), \
             patch.object(app, "clear_screen"), patch.object(app, "console"), \
             patch.object(app, "UpdateDisplay") as display, \
             patch.object(app.readchar, "readkey", return_value=" "):
            with self.assertRaises(SystemExit):
                app._run_update_flow({"kind": "pip"})
        display.return_value.__enter__.return_value.update.assert_called_once_with("waiting", "queued")

    def test_failed_browser_launch_does_not_claim_it_opened(self):
        with patch("webbrowser.open", return_value=False):
            self.assertFalse(updates.run_update({"kind": "binary"})[0])

    def test_worker_reopens_only_successful_updates_after_three_seconds(self):
        for code in (0, 1):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                status, log = Path(directory)/"status.json", Path(directory)/"update.log"
                events = []
                def sleep(seconds):
                    events.append(("wait", seconds))
                    if seconds == 3:
                        data = json.loads(status.read_text())
                        self.assertEqual(data["state"], "succeeded")
                        self.assertEqual(data["reopen"], "waiting")
                with patch.object(update_worker, "_wait_for_parent", return_value=True), \
                     patch.object(update_worker.time, "sleep", side_effect=sleep), \
                     patch.object(update_worker.subprocess, "run", side_effect=lambda *a, **k: events.append("install") or Mock(returncode=code)), \
                     patch.object(update_worker.subprocess, "CREATE_NEW_CONSOLE", 16, create=True), \
                     patch.object(update_worker.subprocess, "Popen", side_effect=lambda *a, **k: events.append("open")) as popen:
                    update_worker.run_job(123, ["fixture"], status, log, reopen=True)
                data = json.loads(status.read_text())
                if code == 0:
                    self.assertEqual(events, [("wait", 1), "install", ("wait", 3), "open"])
                    popen.assert_called_once_with([update_worker.sys.executable, "-m", "torrent_finder"],
                                                 creationflags=16, close_fds=True)
                    self.assertEqual(data["reopen"], "started")
                else:
                    popen.assert_not_called()
                    self.assertEqual(events, [("wait", 1), "install"])
                    self.assertEqual(data["state"], "failed")

    def test_reopening_failure_does_not_turn_a_completed_install_into_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            status, log = Path(directory)/"status.json", Path(directory)/"update.log"
            with patch.object(update_worker, "_wait_for_parent", return_value=True), \
                 patch.object(update_worker.time, "sleep"), \
                 patch.object(update_worker.subprocess, "run", return_value=Mock(returncode=0)), \
                 patch.object(update_worker.subprocess, "CREATE_NEW_CONSOLE", 16, create=True), \
                 patch.object(update_worker.subprocess, "Popen", side_effect=OSError("fixture failure")):
                update_worker.run_job(123, ["fixture"], status, log, reopen=True)
            data = json.loads(status.read_text())
            self.assertEqual(data["state"], "succeeded")
            self.assertEqual(data["reopen"], "failed")
            self.assertIn("manually", ui.completion_detail(data["reopen"]))

    def test_viewer_counts_down_then_closes_without_waiting_for_a_key(self):
        display = Mock()
        display.started = 0
        display.view = ui.UpdateView()
        with patch.object(ui, "UpdateDisplay") as factory, \
             patch.object(ui, "read_job", side_effect=[
                 {"state": "succeeded", "reopen": "waiting", "reopen_at": 103},
                 {"state": "succeeded", "reopen": "started"},
             ]), \
             patch.object(ui.time, "time", return_value=100), \
             patch.object(ui.time, "monotonic", return_value=1), \
             patch.object(ui.time, "sleep"), patch.object(ui.readchar, "readkey") as key:
            factory.return_value.__enter__.return_value = display
            ui.watch_update(Path("unused.json"), "job")
        self.assertIn("3 seconds", display.update.call_args_list[0].args[1])
        self.assertIn("Starting Torrent Finder", display.update.call_args.args[1])
        key.assert_not_called()

    def test_startup_leaves_countdown_report_for_worker_but_consumes_expired_one(self):
        with tempfile.TemporaryDirectory() as directory:
            status, log = Path(directory)/"status.json", Path(directory)/"update.log"
            status.write_text('{"state":"succeeded", "reopen":"waiting", "reopen_at":103}')
            with patch.object(updates, "_update_files", return_value=(status, log)), \
                 patch.object(updates.time, "time", return_value=100):
                self.assertEqual(updates.consume_update_report(), "")
                self.assertTrue(status.exists())
            with patch.object(updates, "_update_files", return_value=(status, log)), \
                 patch.object(updates.time, "time", return_value=114):
                self.assertIn("successfully", updates.consume_update_report())

    def test_preview_countdown_matches_worker_delay_and_never_reopens(self):
        self.assertEqual(update_worker.REOPEN_DELAY, 3)
        for elapsed, remaining in ((7, 3), (8, 2), (9, 1)):
            self.assertIn(f"in {remaining} second", ui.preview_view(elapsed).detail)
        self.assertIn("Starting Torrent Finder", ui.preview_view(10).detail)
        self.assertNotIn("Reopening", ui.preview_view(7, "failure").detail)


if __name__ == "__main__":
    unittest.main()
