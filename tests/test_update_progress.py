import io
import unittest
from unittest.mock import Mock, patch

from rich.console import Console
from rich.padding import Padding
from rich.progress_bar import ProgressBar

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from torrent_finder import main as app, updates
from torrent_finder.ui import update_progress as ui


def _render(view, elapsed=3.0, width=72, notice=""):
    output = io.StringIO()
    Console(file=output, width=width).print(ui.update_panel(view, elapsed, min(72, width), notice))
    return output.getvalue()


def _bar(view, elapsed=3.0) -> ProgressBar:
    return next(part.renderable for part in ui.update_panel(view, elapsed).renderables
                if isinstance(part, Padding))


class UpdateScreenTests(unittest.TestCase):
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

    def test_preview_runs_real_display_without_an_installer(self):
        for outcome in ("success", "failure"):
            output = io.StringIO()
            with patch.object(ui.time, "sleep"), \
                 patch.object(updates, "run_update") as update, \
                 patch.object(updates, "_stream") as stream, \
                 patch.object(updates.subprocess, "Popen") as popen:
                ui.preview_update(outcome, console=Console(file=output, width=48), pause=False)
            self.assertIn("PREVIEW", output.getvalue())
            self.assertIn("Update complete" if outcome == "success" else "Update did not complete", output.getvalue())
            update.assert_not_called()
            stream.assert_not_called()
            popen.assert_not_called()

    def test_ctrl_c_in_preview_exits_without_a_traceback(self):
        with patch("sys.argv", ["torrent-finder", "--preview-update"]), \
             patch.object(app, "preview_update", side_effect=KeyboardInterrupt), \
             patch.object(app, "record_session_start") as stats:
            app.main()
        stats.assert_not_called()

    def test_preview_walks_through_the_real_stages(self):
        def stages(outcome):
            seen = []
            for tick in range(int(ui.PREVIEW_SECONDS[outcome] * 10) + 1):
                stage = ui.preview_view(tick / 10, outcome).stage
                if not seen or seen[-1] != stage:
                    seen.append(stage)
            return seen
        self.assertEqual(stages("success"), ["preparing", "downloading", "installing", "finishing", "succeeded"])
        self.assertEqual(stages("failure"), ["preparing", "downloading", "installing", "failed"])
        self.assertTrue(any(ui.preview_view(tick / 10).total for tick in range(70)))

    def test_download_shows_its_percentage_bytes_and_a_filling_bar(self):
        view = ui.UpdateView("downloading", "torrent_finder_cli-0.9.1-py3-none-any.whl", done=324_000, total=719_511)
        text = _render(view)
        self.assertIn("Downloading update", text)
        self.assertIn("45%", text)
        self.assertIn("324.0 kB of 719.5 kB", text)
        self.assertIn("torrent_finder_cli-0.9.1-py3-none-any.whl", text)
        bar = _bar(view)
        self.assertEqual((bar.total, bar.completed), (719_511, 324_000))
        self.assertFalse(bar.pulse)

    def test_percentage_reaches_100_only_with_the_last_byte(self):
        self.assertIn("99%", _render(ui.UpdateView("downloading", "", done=719_510, total=719_511)))
        self.assertIn("100%", _render(ui.UpdateView("downloading", "", done=719_511, total=719_511)))

    def test_steps_without_a_measurable_length_pulse_without_percentages(self):
        view = ui.UpdateView("installing", "Installing torrent-finder-cli.")
        self.assertNotIn("%", _render(view))
        self.assertTrue(_bar(view).pulse)
        frames = []
        for elapsed in (2, 2.5):
            console = Console(file=io.StringIO(), width=72, record=True, color_system="truecolor")
            console.print(ui.update_panel(view, elapsed))
            frames.append(console.export_html(inline_styles=True))
        self.assertNotEqual(*frames)
        self.assertIn("Elapsed 00:02", _render(view, elapsed=2.5))

    def test_bar_is_full_only_when_the_update_succeeded(self):
        succeeded, failed = _bar(ui.UpdateView("succeeded", "")), _bar(ui.UpdateView("failed", ""))
        self.assertEqual((succeeded.completed, succeeded.total), (100, 100))
        self.assertEqual(failed.completed, 0)
        self.assertFalse(failed.pulse)
        # A finished download is not a finished update.
        self.assertNotIn("Update complete", _render(ui.UpdateView("downloading", "", done=5, total=5)))

    def test_panels_fit_small_terminals(self):
        for width in (24, 32, 48, 80):
            for tick in range(0, 75, 5):
                with self.subTest(width=width, elapsed=tick / 10):
                    text = _render(ui.preview_view(tick / 10), tick / 10, width)
                    self.assertTrue(all(len(line) <= width for line in text.splitlines()))

    def test_interrupt_note_shows_while_updating_but_not_after(self):
        display = ui.UpdateDisplay(Console(file=io.StringIO(), width=72))
        display.update("installing", "Installing torrent-finder-cli.")
        display.interrupted()
        output = io.StringIO()
        Console(file=output, width=72).print(display.render())
        self.assertIn("Ctrl+C cannot stop an update halfway", output.getvalue())
        display.update("succeeded", "Torrent Finder 0.9.1 is installed.")
        output = io.StringIO()
        Console(file=output, width=72).print(display.render())
        self.assertNotIn("Ctrl+C", output.getvalue())

    def test_installed_version_replaces_the_announced_one_in_the_header(self):
        display = ui.UpdateDisplay(Console(file=io.StringIO(), width=72), current="0.9.0", latest="0.9.1")
        display.update("installing", "Installed torrent-finder-cli 0.9.2.", latest="0.9.2")
        display.update("finishing", "Updating pipx's copy of the torrent-finder command.")
        self.assertEqual(display.view.latest, "0.9.2")


class UpdateFlowTests(unittest.TestCase):
    def _flow(self, result, kind="pip", key=" "):
        display = Mock()
        console = Mock()
        with patch.object(app, "run_update", return_value=result) as run, \
             patch.object(app, "clear_screen"), patch.object(app, "console", console), \
             patch.object(app, "UpdateDisplay") as factory, \
             patch.object(app.readchar, "readkey", side_effect=[key]):
            factory.return_value.__enter__.return_value = display
            try:
                app._run_update_flow({"kind": kind, "current": "0.9.0", "latest": "0.9.1"})
                raised = None
            except BaseException as error:  # noqa: BLE001  # the flow's way out is under test
                raised = error
        prompt = " ".join(str(call.args[0]) for call in console.print.call_args_list)
        return display, run, prompt, raised

    def test_successful_update_asks_for_a_key_then_restarts(self):
        display, run, prompt, raised = self._flow(updates.UpdateResult(True, "Torrent Finder 0.9.1 is installed.", restart=True))
        self.assertIsInstance(raised, updates.RestartRequested)
        display.update.assert_called_with("succeeded", "Torrent Finder 0.9.1 is installed.")
        self.assertIn("restart Torrent Finder", prompt)
        self.assertIs(run.call_args.kwargs["on_progress"], display.update)
        self.assertIs(run.call_args.kwargs["on_interrupt"], display.interrupted)

    def test_failed_update_returns_to_the_app(self):
        display, _run, prompt, raised = self._flow(updates.UpdateResult(False, "The installer stopped."))
        self.assertIsNone(raised)
        display.update.assert_called_with("failed", "The installer stopped.")
        self.assertIn("continue", prompt)

    def test_nothing_new_and_release_pages_do_not_restart(self):
        for kind, result, stage in [("pip", updates.UpdateResult(True, "Torrent Finder is already up to date."), "succeeded"),
                                    ("binary", updates.UpdateResult(True, "Opened the Releases page."), "opened")]:
            with self.subTest(kind=kind):
                display, _run, prompt, raised = self._flow(result, kind)
                self.assertIsNone(raised)
                self.assertEqual(display.update.call_args.args[0], stage)
                self.assertNotIn("restart", prompt)

    def test_ctrl_c_at_the_restart_prompt_quits_instead(self):
        _display, _run, _prompt, raised = self._flow(updates.UpdateResult(True, "Installed.", restart=True), key=KeyboardInterrupt())
        self.assertIsInstance(raised, KeyboardInterrupt)

    def test_main_saves_the_session_then_restarts_in_this_terminal(self):
        events = []
        with patch("sys.argv", ["torrent-finder", "-y", "--theme", "quiet", "-t", "movies", "-q", "dune"]), \
             patch.object(app, "_main_loop", side_effect=updates.RestartRequested), \
             patch.object(app, "record_session_start"), \
             patch.object(app, "add_runtime_seconds", side_effect=lambda seconds: events.append("runtime")), \
             patch.object(app.store, "flush", side_effect=lambda: events.append("flush")), \
             patch.object(app, "console"), \
             patch.object(app, "relaunch", side_effect=lambda args: events.append(("relaunch", args)) or 3):
            with self.assertRaises(SystemExit) as exit_:
                app.main()
        self.assertEqual(exit_.exception.code, 3)
        # The first search is not repeated; the session's options are kept.
        self.assertEqual(events, ["runtime", "flush", ("relaunch", ["--skip-warning", "--theme", "quiet"])])

    def test_restart_that_cannot_start_asks_the_user_to_reopen(self):
        console = Mock()
        with patch("sys.argv", ["torrent-finder"]), \
             patch.object(app, "_main_loop", side_effect=updates.RestartRequested), \
             patch.object(app, "record_session_start"), patch.object(app, "add_runtime_seconds"), \
             patch.object(app.store, "flush"), patch.object(app, "console", console), \
             patch.object(app, "relaunch", side_effect=OSError("missing")):
            with self.assertRaises(SystemExit) as exit_:
                app.main()
        self.assertEqual(exit_.exception.code, 0)
        self.assertIn("Open Torrent Finder again", console.print.call_args.args[0])

    def test_an_unhandled_restart_request_still_exits_cleanly(self):
        self.assertEqual(updates.RestartRequested().code, 0)


if __name__ == "__main__":
    unittest.main()
