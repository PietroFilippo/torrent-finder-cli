"""Background progress and notices repaint idle results and search fields."""

import io
import threading
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import isolation  # noqa: F401
from fake_downloads import FakeManager, install, sample_jobs
from rich.console import Console
from rich.text import Text

from torrent_finder import downloads
from torrent_finder.ui import chrome, prompts, table, theme


class DownloadWatcherTests(unittest.TestCase):
    def exercise(self, screen_kind, palette, manager_present=True):
        theme.apply(palette)
        chrome.clear_messages()
        self.addCleanup(chrome.clear_messages)
        job = sample_jobs()[0]
        job.title = "Example"
        manager = install(self, FakeManager([job]) if manager_present else None)
        screen = Console(file=io.StringIO(), width=120, height=40, legacy_windows=False)
        module = table if screen_kind == "results" else prompts
        stop, worker = threading.Event(), Mock()
        rendered = []

        def thread(*, target, **kwargs):
            worker.target = target
            return worker

        def record(renderable, **kwargs):
            target = Console(file=io.StringIO(), width=120, height=40, legacy_windows=False)
            target.print(renderable)
            rendered.append(target.file.getvalue())

        def write(content, *args):
            rendered.append(Text.from_ansi(content).plain)
            return True

        def read():
            initial = len(rendered)
            ticks = [0]
            with patch.object(manager, "snapshot", wraps=manager.snapshot) if manager else ExitStack() as snapshots:
                def wait(_):
                    ticks[0] += 1
                    if manager and ticks[0] == 5:
                        self.assertEqual(len(rendered), initial)
                        snapshots.assert_not_called()
                        manager.set_state(job.id, "running", done_bytes=job.total_bytes * 3 // 4)
                    if manager and ticks[0] == 10:
                        self.assertEqual(len(rendered), initial + 1)
                        self.assertIn("75%", rendered[-1])
                        manager.set_state(job.id, "done", done_bytes=job.total_bytes, speed_bps=0)
                    return ticks[0] > 20
                with patch.object(stop, "wait", side_effect=wait):
                    worker.target()
                self.assertEqual(len(rendered), initial + (2 if manager else 0))
                if manager:
                    self.assertIn("Example finished", rendered[-1])
                    self.assertIn("1 new", rendered[-1])
                    self.assertEqual(chrome.take_message(), "")
            return module.readchar.key.ESC

        with ExitStack() as stack:
            stack.enter_context(patch.object(module, "console", screen))
            stack.enter_context(patch.object(module.threading, "Event", return_value=stop))
            stack.enter_context(patch.object(module.threading, "Thread", side_effect=thread))
            stack.enter_context(patch.object(module.readchar, "readkey", side_effect=read))
            engine = stack.enter_context(patch.object(downloads, "manager", side_effect=AssertionError("engine started")))
            if screen_kind == "results":
                live = Mock()
                live.__enter__ = Mock(return_value=live)
                live.__exit__ = Mock(return_value=False)
                live.update.side_effect = record
                stack.enter_context(patch.object(table, "Live", return_value=live))
                table.interactive_select([dict(name="Short", source="Nyaa", info_hash="a" * 40,
                                              seeders=10, leechers=1, size=1024)])
            else:
                stack.enter_context(patch.object(prompts, "_write_query_frame", side_effect=write))
                stack.enter_context(patch("sys.stdout", io.StringIO()))
                prompts.get_query_with_shortcut(
                    "> ", screen_renderer=prompts.make_search_screen_renderer("Nyaa", "None", False))
            engine.assert_not_called()

    def test_results_progress_and_completion_in_simple(self):
        self.exercise("results", "quiet")

    def test_results_progress_and_completion_in_athanor(self):
        self.exercise("results", "citrinitas")

    def test_search_progress_and_completion_in_simple(self):
        self.exercise("search", "quiet")

    def test_search_progress_and_completion_in_athanor(self):
        self.exercise("search", "citrinitas")

    def test_idle_screens_do_not_start_the_download_engine(self):
        for screen_kind in ("results", "search"):
            with self.subTest(screen=screen_kind):
                self.exercise(screen_kind, "quiet", manager_present=False)
