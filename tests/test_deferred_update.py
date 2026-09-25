import json
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from torrent_finder import updates, update_worker
from torrent_finder import main as app


class DeferredUpdateTests(unittest.TestCase):
    def test_windows_update_queues_without_running_pipx_in_locked_process(self):
        with patch.object(updates, "needs_exit_before_update", return_value=True), \
             patch.object(updates, "_pipx_install", return_value=True), \
             patch.object(updates, "_schedule_update", return_value=(True, "Queued")) as schedule, \
             patch.object(updates.subprocess, "run") as run:
            self.assertEqual(updates.run_update({"kind": "pip"}), (True, "Queued"))
        schedule.assert_called_once_with(["pipx", "upgrade", "torrent-finder-cli"])
        run.assert_not_called()

    def test_queued_update_exits_app_after_acknowledgment(self):
        with patch.object(app, "run_update", return_value=(True, "Queued")), \
             patch.object(app, "needs_exit_before_update", return_value=True), \
             patch.object(app, "clear_screen"), patch.object(app, "console"), \
             patch.object(app, "UpdateDisplay"), \
             patch.object(app.readchar, "readkey", return_value=" "):
            with self.assertRaises(SystemExit):
                app._run_update_flow({"kind": "pip"})

    def test_worker_waits_before_starting_and_records_real_result(self):
        for code, expected in [(0, "succeeded"), (1, "failed")]:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                status, log = Path(directory)/"status.json", Path(directory)/"update.log"
                events = []
                with patch.object(update_worker, "_wait_for_parent", side_effect=lambda pid: events.append("exit") or True), \
                     patch.object(update_worker.time, "sleep"), \
                     patch.object(update_worker.subprocess, "run", side_effect=lambda *a, **k: events.append("update") or Mock(returncode=code)):
                    update_worker.run_job(123, ["fixture"], status, log)
                self.assertEqual(events, ["exit", "update"])
                self.assertEqual(json.loads(status.read_text())["state"], expected)
                with patch.object(updates, "_update_files", return_value=(status, log)):
                    report = updates.consume_update_report()
                    self.assertEqual(updates.consume_update_report(), "")
                self.assertIn("successfully" if code == 0 else "did not complete", report)

    def test_no_update_if_parent_never_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            status, log = Path(directory)/"status.json", Path(directory)/"update.log"
            with patch.object(update_worker, "_wait_for_parent", return_value=False), \
                 patch.object(update_worker.subprocess, "run") as run:
                update_worker.run_job(123, ["fixture"], status, log)
            run.assert_not_called()
            self.assertEqual(json.loads(status.read_text())["state"], "failed")

    def test_malformed_or_stale_status_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as directory:
            status, log = Path(directory)/"status.json", Path(directory)/"update.log"
            with patch.object(updates, "_update_files", return_value=(status, log)):
                status.write_text('[]')
                self.assertEqual(updates.consume_update_report(), "")
                status.write_text('{"state":"pending","started_at":1}')
                self.assertIn("did not complete", updates.consume_update_report())

    @unittest.skipUnless(sys.platform == "win32", "Windows process handles")
    def test_hidden_helper_observes_process_exit_before_a_benign_command(self):
        with tempfile.TemporaryDirectory() as directory:
            status, log = Path(directory)/"status.json", Path(directory)/"update.log"
            parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.2)"], creationflags=subprocess.CREATE_NO_WINDOW)
            real_popen = subprocess.Popen
            workers = []
            def launch(*args, **kwargs):
                worker = real_popen(*args, **kwargs)
                workers.append(worker)
                return worker
            try:
                with patch.object(updates, "_update_files", return_value=(status, log)), \
                     patch.object(updates.os, "getpid", return_value=parent.pid), \
                     patch.object(updates.subprocess, "Popen", side_effect=launch):
                    ok, message = updates._schedule_update([sys.executable, "-c", "print('fixture updater completed')"])
                self.assertTrue(ok, message)
                workers[0].wait(timeout=10)
                self.assertIsNotNone(parent.poll())
                self.assertEqual(json.loads(status.read_text())["state"], "succeeded")
                self.assertIn("fixture updater completed", log.read_text())
            finally:
                parent.wait(timeout=3)
                for worker in workers:
                    worker.wait(timeout=10)
