"""Direct downloads (Madokami, Libgen, F-Droid) as background jobs, and the way into them."""

import io
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from isolation import SHIPPED_BACKGROUND_DEFAULT, isolate_store
from rich.console import Console

from torrent_finder import acquisition, downloads, main, unpack
from torrent_finder.ui import downloads as downloads_ui, prompts


def wait_for(predicate, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class DirectJobTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.engine = Mock()  # never asked: direct jobs need no aria2c
        self.manager = downloads.JobManager(self.engine)
        self.addCleanup(self.manager.shutdown)
        for target, value in (("torrent_finder.downloads.prepare_download_dir", self.root.name),
                              ("torrent_finder.downloads.unpack.enabled", False)):
            context = patch(target, return_value=value)
            context.start()
            self.addCleanup(context.stop)
        context = patch("torrent_finder.downloads.stats.record_method_complete")
        self.stats = context.start()
        self.addCleanup(context.stop)

    def job(self, job_id):
        return next(job for job in self.manager.snapshot() if job.id == job_id)

    def enqueue(self, fetch, key="/Manga/B/Berserk v01.cbz", **kwargs):
        return self.manager.enqueue_direct("Berserk v01.cbz", fetch, key=key, source="Madokami",
                                           provider_slug="madokami", **kwargs)

    def test_a_fetch_runs_reports_progress_and_finishes(self):
        saved = os.path.join(self.root.name, "Berserk v01.cbz")

        def fetch(cancel_event, progress, note):
            progress(50, 100)
            note("from the library")
            progress(100, 100)
            return [saved]
        job = self.enqueue(fetch)
        self.assertTrue(wait_for(lambda: self.job(job.id).state == "done"))
        done = self.job(job.id)
        self.assertEqual((done.backend, done.files, done.total_bytes), ("direct", (saved,), 100))
        self.assertIn("from the library", done.notes)
        self.stats.assert_not_called()  # a direct download counts no download method, as in the foreground
        self.engine.add_uri.assert_not_called()

    def test_a_failure_says_why(self):
        def fetch(cancel_event, progress, note):
            raise downloads.DirectDownloadError("Madokami did not send the file.")
        job = self.enqueue(fetch)
        self.assertTrue(wait_for(lambda: self.job(job.id).state == "failed"))
        self.assertEqual(self.job(job.id).error, "Madokami did not send the file.")

    def test_stop_cancels_mid_file_and_stays_stopped(self):
        started = threading.Event()

        def fetch(cancel_event, progress, note):
            started.set()
            cancel_event.wait(5)  # as download_file checks between chunks
            return []
        job = self.enqueue(fetch)
        self.assertTrue(started.wait(5))
        self.manager.stop(job.id)
        time.sleep(0.05)
        self.assertEqual(self.job(job.id).state, "stopped")
        self.assertFalse(self.manager.is_busy())

    def test_the_same_file_to_the_same_folder_is_refused_while_it_runs(self):
        release = threading.Event()
        self.enqueue(lambda cancel_event, progress, note: release.wait(5) and [])
        with self.assertRaises(downloads.DuplicateDownloadError):
            self.enqueue(lambda *args: [])
        release.set()

    def test_a_stopped_fetch_stays_tracked_until_it_returns(self):
        """Stop marks the row at once, but its file may still be open: busy, not removable, not repeatable."""
        started, release = threading.Event(), threading.Event()

        def fetch(cancel_event, progress, note):
            started.set()
            release.wait(5)  # a request that ignores Stop for a moment
            return []
        job = self.enqueue(fetch)
        self.assertTrue(started.wait(5))
        self.manager.stop(job.id)
        self.assertEqual(self.job(job.id).state, "stopped")
        self.assertTrue(self.manager.is_busy())  # the quit and update guards still wait
        with self.assertRaises(ValueError):
            self.manager.remove(job.id)
        with self.assertRaises(downloads.DuplicateDownloadError):
            self.enqueue(lambda *args: [])
        self.manager.clear_finished()
        self.assertEqual([j.id for j in self.manager.snapshot()], [job.id])  # kept until the fetch returns
        release.set()
        self.assertTrue(wait_for(lambda: not self.manager.is_busy()))
        self.manager.remove(job.id)

    def test_a_file_saved_before_stop_arrived_is_a_finished_download(self):
        saved = os.path.join(self.root.name, "Berserk v01.cbz")
        started, release = threading.Event(), threading.Event()

        def fetch(cancel_event, progress, note):
            started.set()
            release.wait(5)  # the file is already saved when Stop comes
            return [saved]
        job = self.enqueue(fetch)
        self.assertTrue(started.wait(5))
        self.manager.stop(job.id)
        release.set()
        self.assertTrue(wait_for(lambda: self.job(job.id).state == "done"))
        self.assertEqual(self.job(job.id).files, (saved,))

    def test_direct_groups_keep_no_bookkeeping(self):
        group = "batch-1"
        jobs = [self.enqueue(lambda *args: [os.path.join(self.root.name, f"v{n}.cbz")], key=f"/v{n}", group=group)
                for n in (1, 2)]
        self.assertTrue(wait_for(lambda: all(self.job(j.id).state == "done" for j in jobs)))
        self.manager.clear_finished()
        self.assertEqual((self.manager.snapshot(), self.manager._group_states), ((), {}))

    def test_shutdown_waits_on_the_workers_own_word(self):
        """join() interrupted on CPython 3.11 can call a thread finished while it runs:
        shutdown waits on each worker's completion event instead."""
        started, release = threading.Event(), threading.Event()

        def fetch(cancel_event, progress, note):
            started.set()
            release.wait(5)  # ignores Stop for a moment
            return []
        self.enqueue(fetch)
        self.assertTrue(started.wait(5))
        threading.Timer(0.3, release.set).start()
        with patch.object(threading.Thread, "is_alive", return_value=False):  # as after an interrupted join
            self.manager.shutdown()
        self.assertTrue(all(done.is_set() for done in self.manager._direct_done))

    def test_the_quit_prompt_counts_a_download_still_stopping(self):
        started, release = threading.Event(), threading.Event()

        def fetch(cancel_event, progress, note):
            started.set()
            release.wait(5)
            return []
        job = self.enqueue(fetch)
        self.assertTrue(started.wait(5))
        self.manager.stop(job.id)
        captured = {}

        def choose(items, **kwargs):
            captured.update(items=items, intro=kwargs["intro"])
            return None
        with patch.object(downloads_ui, "current", return_value=self.manager), \
             patch.object(downloads_ui, "arrow_select", side_effect=choose):
            downloads_ui.quit_prompt()
        release.set()
        stop = next(item for item in captured["items"] if item.value == "quit")
        self.assertEqual(stop.label, "Stop 1 download and quit")
        self.assertIn("direct downloads", stop.description)  # not the aria2c wording
        self.assertIn("stopping", " ".join(line.plain for line in captured["intro"]))

    def test_the_downloads_screen_shows_a_download_still_stopping(self):
        started, release = threading.Event(), threading.Event()

        def fetch(cancel_event, progress, note):
            started.set()
            release.wait(5)
            return []
        job = self.enqueue(fetch)
        self.assertTrue(started.wait(5))
        self.manager.stop(job.id)
        with patch.object(downloads_ui, "current", return_value=self.manager):
            stopped = self.job(job.id)
            rows = downloads_ui._rows([stopped])
            sections = [row.label for row in rows if row.value == "section_header"]
            self.assertEqual(sections, ["Active"])  # not under Finished while its file closes
            self.assertIn("stopping", downloads_ui._state_hint(stopped).plain)
            self.assertIn("waiting for its file to close", downloads_ui._description(stopped))
            captured = {}
            with patch.object(downloads_ui, "arrow_select",
                              side_effect=lambda items, **kw: captured.update(items=items)):
                downloads_ui._actions(self.manager, stopped)
            self.assertEqual([item.value for item in captured["items"]], ["open", None])  # no retry or remove yet
            self.assertEqual(downloads_ui._counts([stopped]), (1, 0, 0))  # under way, not finished
            self.assertTrue(downloads_ui.badge().startswith("↓ 1"))
            self.assertEqual(len(downloads_ui.menu_inspect()), 1)
            hint = downloads_ui._state_hint(stopped)
            self.assertTrue(any(span.style for span in hint.spans))  # its colour survives a muted row
        release.set()
        self.assertTrue(wait_for(lambda: not self.manager.stopping(job.id)))

    def test_focus_stays_on_the_same_download_after_its_actions(self):
        first_started, release = threading.Event(), threading.Event()
        blocker = self.enqueue(lambda c, p, n: (first_started.set(), release.wait(5), [])[2], key="/a")
        self.assertTrue(first_started.wait(5))
        other = self.enqueue(lambda c, p, n: (c.wait(5), [])[1], key="/b")
        self.manager.stop(blocker.id)
        starts = []

        def choose(items, **kwargs):
            starts.append(kwargs["start_index"])
            if len(starts) == 1:
                return next(i for i, item in enumerate(items) if item.value == blocker.id)
            return None
        with patch.object(downloads_ui, "current", return_value=self.manager), \
             patch.object(downloads_ui, "arrow_select", side_effect=choose), \
             patch.object(downloads_ui, "_actions", side_effect=lambda m, j: (release.set(),
                                                                               wait_for(lambda: not m.stopping(j.id)))):
            downloads_ui.downloads_screen()
        rows = downloads_ui._rows(self.manager.snapshot())
        self.assertEqual(rows[starts[1]].value, blocker.id)  # not the other download now in its old place
        self.manager.stop(other.id)

    def test_a_file_still_being_written_counts_as_downloading(self):
        started, release = threading.Event(), threading.Event()

        def fetch(cancel_event, progress, note):
            started.set()
            release.wait(5)
            return []
        job = self.enqueue(fetch)
        self.assertTrue(started.wait(5))
        self.assertTrue(self.manager.has_direct("Madokami", "/Manga/B/Berserk v01.cbz", self.root.name))
        self.manager.stop(job.id)
        self.assertTrue(self.manager.has_direct("Madokami", "/Manga/B/Berserk v01.cbz", self.root.name))
        release.set()
        self.assertTrue(wait_for(lambda: not self.manager.has_direct("Madokami", "/Manga/B/Berserk v01.cbz",
                                                                       self.root.name)))

    def test_ctrl_c_during_shutdown_still_waits_for_the_direct_workers(self):
        started = threading.Event()

        def fetch(cancel_event, progress, note):
            started.set()
            cancel_event.wait(5)
            return []
        self.enqueue(fetch)
        self.assertTrue(started.wait(5))
        done = self.manager._direct_done[0]
        real_wait, calls = done.wait, []

        def interrupted(timeout=None):
            calls.append(timeout)
            if len(calls) == 1:
                raise KeyboardInterrupt
            return real_wait(timeout)
        with patch.object(done, "wait", side_effect=interrupted):
            self.manager.shutdown()
        self.assertTrue(all(event.is_set() for event in self.manager._direct_done))

    def test_page_archives_unpack_as_pages(self):
        saved = os.path.join(self.root.name, "Berserk v01.cbz")
        with patch("torrent_finder.downloads.unpack.enabled", return_value=True), \
             patch.object(unpack, "unpack_all", return_value=unpack.Report()) as unpack_all:
            job = self.enqueue(lambda *args: [saved], expect_pages=True)
            self.assertTrue(wait_for(lambda: self.job(job.id).state == "done"))
        self.assertTrue(unpack_all.call_args.kwargs["expect_pages"])


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)
        downloads_ui_state = patch.object(downloads_ui, "enabled", return_value=True)
        downloads_ui_state.start()
        self.addCleanup(downloads_ui_state.stop)
        self.folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.folder, True))
        for target in ("torrent_finder.ui.prompts.download_dir_ready",):
            context = patch(target, return_value=True)
            context.start()
            self.addCleanup(context.stop)
        context = patch("torrent_finder.constants.get_download_dir", return_value=self.folder)
        context.start()
        self.addCleanup(context.stop)
        # The app's one download manager is never created by these tests.
        context = patch.object(downloads, "manager", return_value=Mock(active=lambda: ()))
        context.start()
        self.addCleanup(context.stop)

    def test_a_libgen_pick_queues_and_returns_at_once(self):
        prompt = Mock(return_value="next")
        with patch.object(acquisition, "queue_background", side_effect=lambda f, *a: (list(f), [])) as queue, \
             patch.object(downloads_ui, "background_started_prompt", prompt), \
             patch("torrent_finder.libgen.resolve_download_url") as resolve:
            outcome = acquisition.LibgenAcquisition().pick({"name": "Dune", "lg_md5": "abc", "lg_ext": "epub",
                                                            "source": "Libgen"})
        self.assertEqual(outcome.action, "next")
        resolve.assert_not_called()  # the link is resolved inside the job
        fetch = queue.call_args.args[0][0]
        self.assertEqual((fetch.title, fetch.key, fetch.folder), ("Dune", "abc", self.folder))
        self.assertTrue(prompt.call_args.kwargs["back_to_results"])

    def test_a_libgen_job_resolves_then_downloads(self):
        fetch = acquisition.LibgenAcquisition().background_fetch(
            {"name": "Dune", "lg_md5": "abc", "lg_ext": "epub", "page_url": "https://libgen.example/abc"}, self.folder)
        with patch("torrent_finder.libgen.resolve_download_url", return_value="https://cdn.example/f") as resolve, \
             patch("torrent_finder.libgen.download_file", return_value="/x/Dune.epub") as download:
            self.assertEqual(fetch.fetch(threading.Event(), Mock(), Mock()), ["/x/Dune.epub"])
        resolve.assert_called_once()
        self.assertEqual(download.call_args.args[:3], ("https://cdn.example/f", self.folder, "libgen-abc.epub"))
        with patch("torrent_finder.libgen.resolve_download_url", return_value=None):
            with self.assertRaises(downloads.DirectDownloadError) as failure:
                fetch.fetch(threading.Event(), Mock(), Mock())
        self.assertIn("https://libgen.example/abc", str(failure.exception))

    def test_a_madokami_folder_pick_queues_each_chosen_file_together(self):
        files = ["/Manga/B/BE/BERS/Berserk/Berserk v01.cbz", "/Manga/B/BE/BERS/Berserk/Berserk v02.cbz"]
        adapter = acquisition.MadokamiAcquisition()
        with patch("torrent_finder.credentials.madokami_config", return_value={"username": "u", "password": "p"}), \
             patch.object(adapter, "_choose_files", return_value=files), \
             patch.object(acquisition, "queue_background", side_effect=lambda f, *a: (list(f), [])) as queue, \
             patch.object(downloads_ui, "background_started_prompt", return_value="back"):
            outcome = adapter.pick({"name": "Berserk", "mdk_path": "/Manga/B/BE/BERS/Berserk", "source": "Madokami"})
        self.assertEqual(outcome.action, "back")
        fetches = queue.call_args.args[0]
        self.assertEqual([f.key for f in fetches], files)
        self.assertTrue(all(f.expect_pages for f in fetches))
        self.assertEqual({os.path.basename(f.folder) for f in fetches}, {"Berserk"})  # kept together

    def test_an_f_droid_job_notes_the_version(self):
        fetch = acquisition.FDroidAcquisition().background_fetch(
            {"name": "VLC", "fd_package": "org.videolan.vlc", "page_url": "https://f-droid.org/packages/x"}, self.folder)
        note = Mock()
        with patch("torrent_finder.fdroid.suggested_apk", return_value=("https://f-droid.org/repo/vlc.apk", "3.6", 4)), \
             patch("torrent_finder.fdroid.download_apk", return_value="/x/vlc.apk"):
            self.assertEqual(fetch.fetch(threading.Event(), Mock(), note), ["/x/vlc.apk"])
        noted = " ".join(call.args[0] for call in note.call_args_list)
        self.assertIn("3.6", noted)
        self.assertIn("4 builds", noted)

    def test_with_background_off_the_pick_holds_the_screen_and_says_so(self):
        screen = Console(file=io.StringIO(), width=200, color_system=None)
        with patch.object(downloads_ui, "enabled", return_value=False), \
             patch.object(acquisition, "console", screen), \
             patch.object(acquisition.readchar, "readkey"), \
             patch("torrent_finder.libgen.resolve_download_url", return_value=None):
            outcome = acquisition.LibgenAcquisition().pick({"name": "Dune", "lg_md5": "abc", "page_url": "u"})
        self.assertEqual(outcome.action, "back")
        self.assertIn("Tip: with Downloads run: in background", screen.file.getvalue())


class BatchTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)

    def test_a_batch_queues_its_direct_downloads_and_hands_off_the_rest(self):
        results = [{"name": "Dune", "lg_md5": "abc", "source": "Libgen"},
                   {"name": "Dune torrent", "info_hash": "a" * 40, "source": "Apibay"}]
        provider = Mock(slug="books")
        with patch.object(main, "_background_on", return_value=True), \
             patch("torrent_finder.ui.prompts.download_dir_ready", return_value=True), \
             patch.object(acquisition, "queue_background", side_effect=lambda f, *a: (list(f), [])) as queue, \
             patch.object(main, "_batch_handoff_run", return_value=("next", [])) as handoff, \
             patch.object(main, "provider_for_result", return_value=provider), \
             patch.object(main, "record_torrent_picked"):
            self.assertEqual(main._batch_handoff(provider, results, [0, 1]), "next")
        self.assertEqual(queue.call_args.args[1], "Libgen")
        self.assertEqual(handoff.call_args.args[2], [1])  # only the torrent goes to the client
        self.assertIn("1 direct download queued in Downloads", handoff.call_args.kwargs["extra_lines"])

    def test_a_failure_part_way_never_downloads_the_queued_ones_again(self):
        results = [{"name": "Dune", "lg_md5": "abc", "source": "Libgen"},
                   {"name": "VLC", "fd_package": "org.videolan.vlc", "source": "F-Droid"},
                   {"name": "Dune torrent", "info_hash": "a" * 40, "source": "Apibay"}]
        provider = Mock(slug="books")

        def queue(fetches, source, slug=""):
            if source == "F-Droid":
                raise acquisition.QueueFailure([], [], OSError("disk full"))
            return list(fetches), []
        with patch.object(main, "_background_on", return_value=True), \
             patch("torrent_finder.ui.prompts.download_dir_ready", return_value=True), \
             patch.object(acquisition, "queue_background", side_effect=queue), \
             patch.object(main, "_batch_handoff_run", return_value=("next", [])) as handoff, \
             patch.object(main, "provider_for_result", return_value=provider), \
             patch.object(main, "record_torrent_picked"):
            main._batch_handoff(provider, results, [0, 1, 2])
        self.assertEqual(handoff.call_args.args[2], [1, 2])  # Libgen stays queued; F-Droid falls back

    def test_a_batch_already_downloading_starts_nothing_and_records_nothing(self):
        results = [{"name": "Dune", "lg_md5": "abc", "source": "Libgen"}]
        provider = Mock(slug="books")
        with patch.object(main, "_background_on", return_value=True), \
             patch("torrent_finder.ui.prompts.download_dir_ready", return_value=True), \
             patch.object(acquisition, "queue_background", side_effect=lambda f, *a: ([], list(f))), \
             patch.object(main, "provider_for_result", return_value=provider), \
             patch.object(main, "record_torrent_picked") as record, \
             patch.object(main, "_batch_handoff_run") as handoff, \
             patch.object(downloads_ui, "background_started_prompt") as prompt:
            self.assertEqual(main._batch_handoff(provider, results, [0]), "results")
        record.assert_not_called()
        handoff.assert_not_called()  # already downloading: not again in the foreground
        prompt.assert_not_called()  # and no "started" confirmation for nothing new

    def test_items_not_reached_after_a_failure_are_not_downloaded_twice(self):
        results = [{"name": "Dune", "lg_md5": "abc", "source": "Libgen"},
                   {"name": "VLC", "fd_package": "org.videolan.vlc", "source": "F-Droid"}]
        provider = Mock(slug="books")
        running = Mock(has_direct=lambda source, key, folder: source == "F-Droid")
        with patch.object(main, "_background_on", return_value=True), \
             patch("torrent_finder.ui.prompts.download_dir_ready", return_value=True), \
             patch.object(acquisition, "queue_background",
                          side_effect=acquisition.QueueFailure([], [], OSError("disk full"))), \
             patch.object(downloads, "current", return_value=running), \
             patch.object(main, "_batch_handoff_run", return_value=("next", [])) as handoff, \
             patch.object(main, "provider_for_result", return_value=provider), \
             patch.object(main, "record_torrent_picked"):
            main._batch_handoff(provider, results, [0, 1])
        self.assertEqual(handoff.call_args.args[2], [0])  # VLC is already downloading in the background

    def test_back_to_results_from_an_all_direct_batch_reaches_the_results(self):
        results = [{"name": "Dune", "lg_md5": "abc", "source": "Libgen"}]
        provider = Mock(slug="books")
        with patch.object(main, "_background_on", return_value=True), \
             patch("torrent_finder.ui.prompts.download_dir_ready", return_value=True), \
             patch.object(acquisition, "queue_background", side_effect=lambda f, *a: (list(f), [])), \
             patch.object(main, "provider_for_result", return_value=provider), \
             patch.object(main, "record_torrent_picked"), \
             patch.object(downloads_ui, "background_started_prompt", return_value="back"), \
             patch("torrent_finder.ui.prompts.batch_download_menu", return_value="open") as menu, \
             patch.object(main, "clear_screen"):
            self.assertEqual(main._batch_flow(provider, results, [0]), "back")
        menu.assert_called_once()  # straight back to the results, not the batch menu again

    def test_a_foreground_batch_of_direct_downloads_shows_the_tip(self):
        results = [{"name": "Dune", "lg_md5": "abc", "source": "Libgen"}]
        with patch.object(main, "_background_on", return_value=False), \
             patch.object(main, "_print_background_tip") as tip, \
             patch.object(main, "_batch_handoff_run", return_value=("next", [])):
            main._batch_handoff(Mock(slug="books"), results, [0])
        tip.assert_called_once()

    def test_an_all_direct_batch_confirms_like_a_single_download(self):
        results = [{"name": "Dune", "lg_md5": "abc", "source": "Libgen"}]
        provider = Mock(slug="books")
        with patch.object(main, "_background_on", return_value=True), \
             patch("torrent_finder.ui.prompts.download_dir_ready", return_value=True), \
             patch.object(acquisition, "queue_background", side_effect=lambda f, *a: (list(f), [])), \
             patch.object(main, "_batch_handoff_run") as handoff, \
             patch.object(main, "provider_for_result", return_value=provider), \
             patch.object(main, "record_torrent_picked"), \
             patch.object(downloads_ui, "background_started_prompt", return_value="next") as prompt:
            self.assertEqual(main._batch_handoff(provider, results, [0]), "next")
        handoff.assert_not_called()
        self.assertTrue(prompt.call_args.kwargs["back_to_results"])


class WayInTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)

    def test_background_downloads_are_on_unless_turned_off(self):
        self.assertTrue(SHIPPED_BACKGROUND_DEFAULT)
        with patch.object(downloads_ui, "DEFAULT_ENABLED", SHIPPED_BACKGROUND_DEFAULT):
            self.assertTrue(downloads_ui.enabled())  # nothing saved: on
            from torrent_finder.state import save_setting
            save_setting(downloads_ui.SETTING, False)
            self.assertFalse(downloads_ui.enabled())  # turned off: stays off

    def test_with_the_shipped_default_a_pick_goes_to_the_background(self):
        with patch.object(downloads_ui, "DEFAULT_ENABLED", SHIPPED_BACKGROUND_DEFAULT), \
             patch("torrent_finder.ui.prompts.download_dir_ready", return_value=True), \
             patch("torrent_finder.constants.get_download_dir", return_value=tempfile.gettempdir()), \
             patch.object(downloads, "manager", return_value=Mock(active=lambda: ())), \
             patch.object(acquisition, "queue_background", side_effect=lambda f, *a: (list(f), [])) as queue, \
             patch.object(downloads_ui, "background_started_prompt", return_value="back"):
            acquisition.LibgenAcquisition().pick({"name": "Dune", "lg_md5": "abc", "source": "Libgen"})
        queue.assert_called_once()

    def test_toggling_the_switch_updates_the_aria2c_row_at_once(self):
        captured = {}

        def choose(items, **kwargs):
            captured["items"] = items
            row = next(i for i, item in enumerate(items) if item.value == "toggle_background")
            kwargs["on_action"](row, items)
            return None
        with patch.object(downloads_ui, "DEFAULT_ENABLED", True), \
             patch.object(prompts, "has_aria2", return_value=True), \
             patch.object(prompts, "arrow_select", side_effect=choose):
            prompts.download_method_prompt("magnet:?xt=urn:btih:" + "a" * 40)
        aria = next(item for item in captured["items"] if item.value == "aria")
        self.assertIn("holds this screen", aria.hint)  # switched off: the row says so

    def test_the_quit_prompt_says_what_stopping_loses(self):
        torrent, direct = Mock(backend="aria2c"), Mock(backend="direct")
        self.assertIn("resumes", downloads_ui._stop_consequences([torrent]))
        self.assertIn("starts over", downloads_ui._stop_consequences([direct]))
        both = downloads_ui._stop_consequences([torrent, direct])
        self.assertIn("partial files", both)
        self.assertIn("start over", both)

    def test_the_aria2c_row_says_where_it_runs(self):
        for on, words in ((True, "keeps going while you search"), (False, "holds this screen")):
            with self.subTest(on=on):
                captured = []

                def choose(items, **kwargs):
                    captured.append(items)
                    return None
                with patch.object(downloads_ui, "enabled", return_value=on), \
                     patch.object(prompts, "has_aria2", return_value=True), \
                     patch.object(prompts, "arrow_select", side_effect=choose):
                    prompts.download_method_prompt("magnet:?xt=urn:btih:" + "a" * 40)
                aria = next(item for item in captured[0] if item.value == "aria")
                self.assertIn(words, aria.hint)

    def test_the_download_folder_screen_holds_the_switch(self):
        captured = []

        def choose(items, **kwargs):
            captured.append((items, kwargs))
            return None
        with patch.object(prompts, "arrow_select", side_effect=choose):
            prompts.download_dir_prompt()
        items, kwargs = captured[0]
        row = next(item for item in items if item.value == "__background__")
        self.assertEqual(row.label, downloads_ui.setting_label())
