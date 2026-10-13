"""Background job lifecycle without terminals, settings or network services."""
import base64
from contextlib import redirect_stdout, redirect_stderr
import io
import os
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import isolation  # noqa: F401
from torrent_finder import downloads, i18n, unpack


class FakeRPC:
    def __init__(self, root):
        self.log_path = os.path.join(root, "aria2.log")
        self.proc = Mock()
        self.calls = []
        self.replies = {}
        self.failure = None
        self.alive = True

    def add_uri(self, uri, folder, select):
        gid = str(len([c for c in self.calls if c[0] == "add"]) + 1)
        self.calls.append(("add", uri, folder, select))
        self.replies[gid] = {"status": "waiting"}
        return gid

    def statuses(self, gids):
        self.calls.append(("poll", gids))
        if self.failure:
            raise self.failure
        return tuple(self.replies[gid] for gid in gids)

    def remove(self, gid):
        self.calls.append(("remove", gid))

    def remove_result(self, gid):
        self.calls.append(("remove_result", gid))

    def log_tail(self):
        return "disk full"

    def is_alive(self):
        return self.alive

    def shutdown(self, graceful=True):
        self.calls.append(("shutdown", graceful))
        self.alive = False


class BackgroundDownloadsTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.rpc = FakeRPC(self.root.name)
        self.manager = downloads.JobManager(self.rpc)
        self.addCleanup(self.manager.shutdown)
        for target, value in (("torrent_finder.downloads.prepare_download_dir", self.root.name),
                              ("torrent_finder.downloads.unpack.enabled", False)):
            context = patch(target, return_value=value)
            context.start()
            self.addCleanup(context.stop)
        context = patch("torrent_finder.downloads.stats.record_method_complete")
        self.stats = context.start()
        self.addCleanup(context.stop)
        # Most cases drive one poll/finish deterministically. A separate test
        # exercises the real two workers, rather than waiting in every case.
        self.workers = patch.object(self.manager, "_start_workers")
        self.workers.start()
        self.addCleanup(self.workers.stop)

    def test_a_given_folder_is_used_instead_of_the_setting(self):
        own = os.path.join(self.root.name, "own")
        with patch("torrent_finder.downloads.prepare_download_dir",
                   side_effect=lambda folder=None: folder or self.root.name) as prepare:
            job = self.enqueue(folder=own)
        prepare.assert_called_once_with(own)
        self.assertEqual(job.target_dir, os.path.abspath(own))

    def enqueue(self, uri="http://local.test/file", select=None, **kwargs):
        return self.manager.enqueue_aria2("Example", uri, select, source="Nyaa",
                                          provider_slug="anime", method="aria", **kwargs)

    def job(self, job_id):
        return next(j for j in self.manager.snapshot() if j.id == job_id)

    def poll(self, job, **status):
        self.rpc.replies[self.job(job.id).gid] = status
        self.manager._poll_once()
        return self.job(job.id)

    def finish_pending(self):
        while True:
            try:
                job_id = self.manager._finish_queue.get_nowait()
            except queue.Empty:
                return
            try:
                if job_id is not None:
                    self.manager._finish(job_id)
            finally:
                self.manager._finish_queue.task_done()

    def complete(self, job, files=()):
        self.poll(job, status="complete", completedLength="100", totalLength="100", files=list(files))
        self.finish_pending()
        return self.job(job.id)

    def test_queued_metadata_handoff_running_done(self):
        job = self.enqueue("magnet:?xt=urn:btih:" + "a" * 40, [3, 1])
        self.assertEqual(job.state, "queued")
        self.assertEqual(self.rpc.calls[0][3], (1, 3))
        job = self.poll(job, status="active", totalLength="400", completedLength="200")
        self.assertEqual(job.state, "metadata")
        self.assertIsNone(job.progress)
        self.poll(job, status="complete")  # handoff not visible yet
        self.assertEqual(self.job(job.id).state, "metadata")
        self.stats.assert_not_called()
        self.rpc.replies["payload"] = {"status": "waiting"}
        job = self.poll(job, status="complete", followedBy=["payload"])
        self.assertEqual(job.gid, "payload")
        self.assertIn(("remove_result", "1"), self.rpc.calls)
        self.assertEqual(self.poll(job, status="waiting").state, "queued")
        job = self.poll(job, status="active", completedLength="30", totalLength="100", downloadSpeed="10",
                        connections="5", numSeeders="2")
        self.assertEqual((job.state, job.progress, job.eta_s, job.peers, job.seeds), ("running", .3, 7, 5, 2))
        done = self.complete(job, [{"path": "exact/file.cbz", "selected": "true"},
                                   {"path": "unselected.cbz", "selected": "false"}])
        self.assertEqual((done.state, done.files, done.speed_bps), ("done", ("exact/file.cbz",), 0))
        self.assertIsNotNone(done.started_at)
        self.assertIsNotNone(done.finished_at)
        self.assertIn(("remove_result", "payload"), self.rpc.calls)
        self.stats.assert_called_once_with("aria")
        self.manager._poll_once()
        self.stats.assert_called_once()

    def test_error_contains_message_and_log_tail(self):
        job = self.poll(self.enqueue(), status="error", errorMessage="No space left", errorCode="9")
        self.assertEqual(job.state, "failed")
        self.assertIn("No space left", job.error)
        self.assertIn("disk full", " ".join(job.notes))
        self.assertEqual(job.log_path, self.rpc.log_path)
        self.assertIn(("remove_result", job.gid), self.rpc.calls)
        self.stats.assert_not_called()

    def test_stop_removes_gid_and_never_records_completion(self):
        job = self.enqueue()
        self.manager.stop(job.id)
        self.manager.stop(job.id)
        self.assertEqual(self.rpc.calls.count(("remove", job.gid)), 1)
        self.assertEqual(self.job(job.id).state, "stopped")
        self.assertTrue(self.job(job.id).cancel_event.is_set())
        self.manager._poll_once()
        self.stats.assert_not_called()
        # Stop leaves a resumable identity available for a new job.
        self.assertNotEqual(self.enqueue().id, job.id)

    def test_stop_failure_does_not_claim_stopped(self):
        job = self.enqueue()
        with patch.object(self.rpc, "remove", side_effect=RuntimeError("RPC unavailable")):
            with self.assertRaisesRegex(RuntimeError, "RPC unavailable"):
                self.manager.stop(job.id)
        self.assertEqual(self.job(job.id).state, "queued")

    def test_stop_wins_over_pending_finisher(self):
        job = self.poll(self.enqueue(), status="complete")
        self.manager.stop(job.id)
        self.finish_pending()
        self.assertEqual(self.job(job.id).state, "stopped")
        self.assertFalse(any(c[0] == "remove" for c in self.rpc.calls))
        self.stats.assert_not_called()

    def test_update_guard_stays_busy_until_a_stopped_finisher_returns(self):
        job = self.poll(self.enqueue(), status="complete")
        with patch.object(downloads, "_manager", self.manager):
            self.manager.stop(job.id)
            self.assertEqual(self.manager.active(), ())
            self.assertTrue(downloads.busy())
            self.finish_pending()
            self.assertFalse(downloads.busy())
        self.stats.assert_not_called()

    def test_batch_records_once_after_every_member_succeeds(self):
        with self.manager.batch():
            first = self.enqueue(group="batch")
            second = self.enqueue("http://local.test/second", group="batch")
        self.complete(first)
        self.stats.assert_not_called()
        self.complete(second)
        self.stats.assert_called_once_with("aria")
        self.complete(self.enqueue("http://local.test/standalone"))
        self.assertEqual(self.stats.call_count, 2)

    def test_batch_enrollment_blocks_poller_but_not_snapshot_readers(self):
        entered, finished = threading.Event(), threading.Event()

        def poll():
            entered.set()
            self.manager._poll_once()
            finished.set()

        with self.manager.batch():
            first = self.enqueue(group="batch")
            self.rpc.replies[first.gid] = {"status": "complete"}
            worker = threading.Thread(target=poll)
            worker.start()
            self.assertTrue(entered.wait(2))
            self.assertFalse(finished.is_set())
            second = self.enqueue("http://local.test/second", group="batch")
            self.assertEqual(len(self.manager.snapshot()), 2)
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.finish_pending()
        self.stats.assert_not_called()
        self.complete(second)
        self.stats.assert_called_once()

    def test_failed_or_stopped_batch_never_counts_even_after_clearing(self):
        for terminal in ("error", "removed"):
            with self.subTest(terminal=terminal):
                first = self.enqueue("http://local.test/" + terminal, group=terminal)
                second = self.enqueue("http://local.test/second-" + terminal, group=terminal)
                self.poll(first, status=terminal, errorMessage="failed")
                self.manager.clear_finished()
                self.complete(second)
        self.stats.assert_not_called()

    def test_unpack_is_disabled_unless_setting_is_on(self):
        with patch.object(unpack, "unpack_all") as run:
            self.complete(self.enqueue(), [{"path": "exact.cbz", "selected": "true"}])
            run.assert_not_called()

    def test_unpack_uses_exact_selected_rpc_paths_after_result_removed(self):
        job = self.enqueue()

        def run(paths, *, status):
            self.assertIn(("remove_result", job.gid), self.rpc.calls)
            self.assertEqual(paths, ("exact.cbz",))
            self.assertEqual(self.job(job.id).state, "unpacking")
            status("Unpacking 1/1 exact.cbz")
            return unpack.Report(["pages"], [("kept.cbr", "damaged")])

        with patch.object(unpack, "enabled", return_value=True), patch.object(unpack, "unpack_all", side_effect=run):
            done = self.complete(job, [{"path": "exact.cbz", "selected": "true"},
                                       {"path": "ignored.cbz", "selected": "false"}])
        self.assertIn("Unpacking 1/1 exact.cbz", done.notes)
        self.assertIn("Unpacked into pages", done.notes)
        self.assertIn("Kept kept.cbr packed: damaged", done.notes)

    def test_unpack_permission_error_retries(self):
        with patch.object(unpack, "enabled", return_value=True), \
                patch.object(unpack, "unpack_all", side_effect=[PermissionError("Defender"), unpack.Report()]) as run:
            self.assertEqual(self.complete(self.enqueue()).state, "done")
            self.assertEqual(run.call_count, 2)

    def test_locked_archive_open_retries_before_unpacking(self):
        job = self.enqueue()
        opened = Mock()
        opened.__enter__ = Mock()
        opened.__exit__ = Mock()
        with patch.object(unpack, "enabled", return_value=True), \
                patch.object(unpack, "unpack_all", return_value=unpack.Report()) as run, \
                patch("builtins.open", side_effect=[PermissionError("Defender"), opened]) as open_file:
            self.assertEqual(self.complete(job, [{"path": "exact.cbz", "selected": "true"}]).state, "done")
        self.assertEqual(open_file.call_count, 2)
        run.assert_called_once()

    def test_finisher_exception_does_not_strand_later_jobs(self):
        first = self.enqueue()
        second = self.enqueue("http://local.test/second")
        with patch.object(unpack, "enabled", return_value=True), \
                patch.object(unpack, "unpack_all", side_effect=RuntimeError("unpack failed")):
            self.assertEqual(self.complete(first).state, "failed")
        self.assertEqual(self.complete(second).state, "done")
        self.stats.assert_called_once()

    def test_stop_during_unpack_suppresses_completion_stats(self):
        job = self.enqueue()

        def unpack_and_stop(*args, **kwargs):
            self.manager.stop(job.id)
            return unpack.Report()

        with patch.object(unpack, "enabled", return_value=True), \
                patch.object(unpack, "unpack_all", side_effect=unpack_and_stop):
            self.complete(job)
        self.assertEqual(self.job(job.id).state, "stopped")
        self.stats.assert_not_called()

    def test_duplicate_hash_folder_and_selection_are_refused(self):
        hex_hash = "aa" * 20
        b32_hash = base64.b32encode(bytes.fromhex(hex_hash)).decode()
        job = self.enqueue("magnet:?xt=urn:btih:" + hex_hash + "&dn=old", [2, 1])
        with self.assertRaisesRegex(downloads.DuplicateDownloadError, "already downloading"):
            self.enqueue("magnet:?xt=urn:btih:" + b32_hash + "&dn=new", [1, 2, 2])
        self.enqueue("magnet:?xt=urn:btih:" + hex_hash, [1])  # different selection
        with patch("torrent_finder.downloads.prepare_download_dir", return_value=os.path.join(self.root.name, "elsewhere")):
            self.enqueue(job.magnet, [1, 2])

    def test_empty_and_zero_file_selections_are_refused(self):
        for selection in ([], [0], [-1]):
            with self.assertRaisesRegex(ValueError, "1-based"):
                self.enqueue(select=selection)
        self.assertEqual(self.rpc.calls, [])

    def test_snapshot_and_enqueue_results_do_not_mutate_owned_jobs(self):
        job = self.enqueue()
        job.state = "done"
        job.cancel_event.set()
        snap = self.manager.snapshot()[0]
        snap.notes += ("outside",)
        snap.cancel_event.set()
        self.assertEqual(self.job(job.id).state, "queued")
        self.assertEqual(self.job(job.id).notes, ())
        self.assertFalse(self.job(job.id).cancel_event.is_set())

    def test_completion_is_silent_to_stdout_stderr_and_rich_console(self):
        out, err, console_out = io.StringIO(), io.StringIO(), io.StringIO()
        from rich.console import Console
        from torrent_finder import constants
        console = Console(file=console_out, force_terminal=True)
        with redirect_stdout(out), redirect_stderr(err), patch.object(constants, "console", console), \
                patch.object(console, "status") as status, patch.object(console, "print") as print_call:
            with patch.object(unpack, "enabled", return_value=True), \
                    patch.object(unpack, "unpack_all", return_value=unpack.Report(["pages"])):
                self.complete(self.enqueue())
            self.poll(self.enqueue(), status="error", errorMessage="bad")
            status.assert_not_called()
            print_call.assert_not_called()
        self.assertEqual((out.getvalue(), err.getvalue(), console_out.getvalue()), ("", "", ""))

    def test_revision_and_hooks_publish_states_but_throttle_progress(self):
        hook = Mock(side_effect=lambda: self.manager.snapshot())
        self.manager.on_change.extend([Mock(side_effect=ValueError), hook])
        with patch("torrent_finder.downloads.time.monotonic", return_value=100):
            job = self.enqueue()
            rev = self.manager.revision
            self.poll(job, status="active", totalLength="100", completedLength="1")
            self.assertGreater(self.manager.revision, rev)
            rev = self.manager.revision
            self.poll(job, status="active", totalLength="100", completedLength="2")
            self.assertEqual(self.manager.revision, rev + 1)
            self.poll(job, status="active", totalLength="100", completedLength="3")
            self.assertEqual(self.manager.revision, rev + 1)
            self.poll(job, status="paused", totalLength="100", completedLength="3")
            self.assertEqual(self.manager.revision, rev + 2)
        with patch("torrent_finder.downloads.time.monotonic", return_value=101):
            self.poll(job, status="paused", totalLength="100", completedLength="4")
            self.assertEqual(self.manager.revision, rev + 3)
        self.assertEqual(hook.call_count, 5)

    def test_summary_furthest_progress_total_speed_unseen_and_busy(self):
        with patch.object(downloads, "_manager", self.manager):
            self.assertFalse(downloads.busy())
            first = self.enqueue()
            second = self.enqueue("http://local.test/second")
            self.assertTrue(downloads.busy())
            self.poll(first, status="active", completedLength="20", totalLength="100", downloadSpeed="10")
            self.poll(second, status="active", completedLength="60", totalLength="100", downloadSpeed="30")
            self.assertEqual(self.manager.summary(), downloads.Summary(2, .6, 40, 0))
            self.complete(first)
            self.assertEqual(self.manager.summary(), downloads.Summary(1, .6, 30, 1))
            revision = self.manager.revision
            self.manager.mark_seen()
            self.assertGreater(self.manager.revision, revision)
            self.assertEqual(self.manager.summary().unseen_completions, 0)
            self.complete(second)
            self.assertFalse(downloads.busy())
            self.assertEqual(self.manager.summary(), downloads.Summary(0, None, 0, 1))
            self.manager.clear_finished()
            self.assertEqual(self.manager.summary(), downloads.Summary(0, None, 0, 0))

    def test_remove_and_clear_finished_keep_active_jobs(self):
        first = self.enqueue()
        with self.assertRaisesRegex(ValueError, "Stop"):
            self.manager.remove(first.id)
        second = self.enqueue("http://local.test/second")
        self.manager.stop(second.id)
        self.manager.remove(second.id)
        self.manager.clear_finished()
        self.assertEqual([j.id for j in self.manager.active()], [first.id])

    def test_three_failed_polls_check_process_without_kill_probe(self):
        job = self.enqueue()
        self.rpc.failure = OSError("RPC gone")
        with patch("os.kill", side_effect=AssertionError("unsafe probe")):
            self.manager._poll_once()
            self.manager._poll_once()
            self.assertEqual(self.job(job.id).state, "queued")
            self.rpc.alive = False
            self.manager._poll_once()
        self.assertEqual(self.job(job.id).state, "interrupted")
        self.assertIn("disk full", self.job(job.id).error)
        self.stats.assert_not_called()

    def test_live_process_survives_rpc_failure_and_counter_resets_on_success(self):
        job = self.enqueue()
        self.rpc.failure = OSError("temporary")
        for _ in range(3):
            self.manager._poll_once()
        self.assertEqual(self.job(job.id).state, "queued")
        self.rpc.failure = None
        self.manager._poll_once()
        self.assertEqual(self.manager._poll_failures, 0)

    def test_snapshot_is_responsive_during_rpc_and_stop_uses_followed_gid(self):
        job = self.enqueue("magnet:?xt=urn:btih:" + "a" * 40)
        entered, release = threading.Event(), threading.Event()

        def slow_status(gids):
            entered.set()
            self.assertTrue(release.wait(3))
            return ({"status": "complete", "followedBy": ["real"]},)

        with patch.object(self.rpc, "statuses", side_effect=slow_status):
            poller = threading.Thread(target=self.manager._poll_once)
            stopper = threading.Thread(target=self.manager.stop, args=(job.id,))
            poller.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(self.manager.snapshot()[0].id, job.id)
                stopper.start()
            finally:
                release.set()
                poller.join(3)
                if stopper.ident is not None:
                    stopper.join(3)
            self.assertFalse(poller.is_alive())
            self.assertFalse(stopper.is_alive())
        self.assertIn(("remove", "real"), self.rpc.calls)

    def test_shutdown_is_idempotent_closes_manager_and_no_pending_stats(self):
        job = self.enqueue()
        self.manager.shutdown()
        self.manager.shutdown()
        self.assertEqual(self.rpc.calls.count(("shutdown", True)), 1)
        self.assertEqual(self.job(job.id).state, "stopped")
        with self.assertRaisesRegex(RuntimeError, "closed"):
            self.enqueue()
        self.stats.assert_not_called()

    def test_real_workers_finish_and_join_on_shutdown(self):
        self.workers.stop()
        job = self.enqueue()
        self.rpc.replies[job.gid] = {"status": "complete", "totalLength": "100", "completedLength": "100"}
        deadline = time.monotonic() + 5
        while self.job(job.id).state != "done" and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertEqual(self.job(job.id).state, "done")
        self.manager.shutdown()
        self.assertFalse(self.manager._poller.is_alive())
        self.assertFalse(self.manager._finisher.is_alive())
        self.stats.assert_called_once()

    def test_lazy_accessor_and_busy_do_not_start_engine(self):
        with patch.object(downloads, "_manager", None), patch.object(downloads, "Aria2Engine") as engine:
            self.assertFalse(downloads.busy())
            first = downloads.manager()
            self.assertIs(first, downloads.manager())
            engine.assert_called_once_with()
            engine.return_value.add_uri.assert_not_called()
            first.shutdown()

    def test_state_labels_follow_current_language_without_changing_identity(self):
        job = self.enqueue()
        expected = ("na fila", "buscando metadados", "baixando", "pausado", "descompactando",
                    "concluído", "falhou", "parado", "interrompido")
        i18n.use("pt-BR")
        try:
            for state, label in zip(downloads._LABELS, expected):
                job.state = state
                self.assertEqual(job.state_label, label)
                self.assertEqual(job.state, state)
        finally:
            i18n.use("en")
