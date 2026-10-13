"""Background downloads on screen: the figure, the Downloads screen, its keys and prompts, the quit and update guards."""

import io
import unittest
import warnings
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirects saved settings before anything reads them
from isolation import isolate_store
from fake_downloads import FRIEREN, GIB, FakeManager, install, sample_jobs
from readchar import key as K
from rich.console import Console

from torrent_finder import downloads, main, state
from torrent_finder.ui import chrome, downloads as downloads_ui, prompts, selector, theme
from torrent_finder.ui.selector import SelectItem


def plain(value) -> str:
    return value.plain if hasattr(value, "plain") else str(value)


def driving(keys, width: int = 100, height: int = 30) -> ExitStack:
    """A real selector drawn headless, answering these key presses in order.

    Frames render in true colour, as in the app: Rich caches a style's escape
    codes on first use, and a frame drawn in 8 colours would leave the section
    style cached that way for the tests after this module.
    """
    from rich.color import ColorSystem
    from torrent_finder import constants
    stack = ExitStack()
    stack.enter_context(patch.object(constants.console, "_color_system", ColorSystem.TRUECOLOR))
    stack.enter_context(patch.object(selector, "console", Console(file=io.StringIO(), width=width, height=height)))
    stack.enter_context(patch.object(selector.sys, "stdout", io.StringIO()))
    stack.enter_context(patch.object(selector.readchar, "readkey", side_effect=list(keys)))
    return stack


def capture(target, module, run) -> dict:
    """Run *run* with *module*.arrow_select replaced: the first call's items and keyword arguments."""
    seen = {}

    def fake(items, **kwargs):
        seen.setdefault("items", items)
        seen.setdefault("kwargs", kwargs)
        return None
    with patch.object(module, "arrow_select", side_effect=fake):
        run()
    return seen


class DownloadsUITests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)
        chrome.clear_messages()
        self.addCleanup(chrome.clear_messages)

    # --- the figure --------------------------------------------------------------------------

    def test_the_status_line_opens_with_the_downloads_figure(self):
        theme.apply("citrinitas", focus="bar", density="comfortable")
        install(self, FakeManager(sample_jobs()))
        line = chrome.status_line(137).plain
        self.assertTrue(line.startswith(" ↓ 2 · 43% · 3.1 MB/s  Searches:"), line)
        self.assertIn("Oct", line)
        narrow = chrome.status_line(60).plain
        self.assertIn("↓ 2 · 43% · 3.1 MB/s", narrow)
        self.assertNotIn("Oct", narrow)  # the date and version give way first

    def test_an_unseen_completion_reads_new_and_opening_downloads_clears_it(self):
        theme.apply("citrinitas", focus="bar", density="comfortable")
        manager = install(self, FakeManager([job for job in sample_jobs() if job.state in downloads.FINISHED_STATES]))
        self.assertIn("↓ ✓2 new", chrome.status_line(100).plain)
        with patch.object(downloads_ui, "arrow_select", return_value=None):
            downloads_ui.downloads_screen()
        self.assertIn(("mark_seen",), manager.calls)
        self.assertNotIn("↓", chrome.status_line(100).plain)

    def test_without_a_background_download_nothing_changes(self):
        theme.apply("citrinitas", focus="bar", density="comfortable")
        install(self, None)
        self.assertNotIn("↓", chrome.status_line(100).plain)
        self.assertIsNone(downloads_ui.figure())
        self.assertEqual(downloads_ui.badge(), "")
        self.assertIsNone(downloads_ui.menu_row())

    def test_simples_header_carries_the_badge(self):
        install(self, FakeManager(sample_jobs()))
        self.assertTrue(prompts.home_status().startswith("↓ 2 · 43% · 3.1 MB/s · v"), prompts.home_status())
        manager = install(self, FakeManager([job for job in sample_jobs() if job.state == "done"][:1]))
        self.assertTrue(prompts.home_status().startswith("↓ [good]✓[/good]1 new · v"))
        manager.mark_seen()
        self.assertTrue(prompts.home_status().startswith("v"))

    # --- the Downloads screen ------------------------------------------------------------------

    def test_rows_show_every_state(self):
        install(self, FakeManager(sample_jobs()))
        items = downloads_ui._rows(sample_jobs())
        headings = [item.label for item in items if item.value == "section_header"]
        self.assertEqual(headings, ["Active", "Finished"])
        hints = {plain(item.label): plain(item.hint) for item in items if item.value not in ("section_header", None)}
        self.assertEqual(hints[FRIEREN], "43% · 3.1 MB/s · 4 min")
        self.assertEqual(hints["Dune Part Two 2024 2160p REMUX"], "fetching metadata")
        self.assertEqual(hints["The Expanse S04 1080p"], "queued")
        self.assertEqual(hints["[SubsPlease] Frieren - 02 (1080p)"], "✓ 1.4 GB")
        self.assertEqual(hints["Blue Giant 2023 1080p"], "failed")
        self.assertEqual(hints["One Piece 1090 (1080p)"], "stopped · 61%")
        self.assertEqual(items[-1].label, "Back")
        focused = next(item for item in items if plain(item.label) == FRIEREN)
        self.assertIn("Saving to D:\\Torrents\\Anime", focused.description)
        self.assertIn("14 peers · 3 seeds", focused.description)
        self.assertIn("Started  14:02 · 4 min left", [line.plain for line in focused.details()])
        failed = next(item for item in items if plain(item.label) == "Blue Giant 2023 1080p")
        self.assertIn("no peers for 10 minutes", failed.description)
        self.assertTrue(any(line.plain.startswith("Log  ") for line in failed.details()))

    def test_failed_and_stopped_keep_their_state_colours_under_a_muted_row(self):
        # The selector draws hints on a muted base: a Text's own base style would be covered.
        items = downloads_ui._rows(sample_jobs())
        for title, role in (("Blue Giant 2023 1080p", theme.BAD), ("One Piece 1090 (1080p)", theme.WARN)):
            with self.subTest(title=title):
                hint = next(item.hint for item in items if plain(item.label) == title).copy()
                hint.stylize_before(theme.MUTED)
                self.assertIn(role, [str(span.style) for span in hint.spans[1:]])

    def test_rows_follow_the_jobs_while_the_screen_is_open(self):
        manager = install(self, FakeManager(sample_jobs()))
        seen = capture(None, downloads_ui, downloads_ui.downloads_screen)
        items, refresh = seen["items"], seen["kwargs"]["refresh"]
        self.assertFalse(refresh())
        manager.set_state("job1", "done", done_bytes=int(1.4 * GIB), speed_bps=0, eta_s=None)
        self.assertTrue(refresh())
        labels = [plain(item.label) for item in items]
        self.assertLess(labels.index("Finished"), labels.index(FRIEREN))  # moved to FINISHED in place
        self.assertEqual(plain(items[labels.index(FRIEREN)].hint), "✓ 1.4 GB")
        self.assertFalse(refresh())

    def test_x_o_and_c_act_on_the_focused_row(self):
        manager = install(self, FakeManager(sample_jobs()))
        with driving(["x", K.ESC]):
            downloads_ui.downloads_screen()
        self.assertIn(("stop", "job1"), manager.calls)
        opened = []
        install(self, FakeManager(sample_jobs()))
        with driving(["o", K.ESC]), patch.object(downloads_ui, "_open_folder", side_effect=lambda p: opened.append(p) or True):
            downloads_ui.downloads_screen()
        self.assertEqual(opened, ["D:\\Torrents\\Anime"])
        manager = install(self, FakeManager(sample_jobs()))
        with driving(["c", K.ESC]):
            downloads_ui.downloads_screen()
        self.assertIn(("clear_finished",), manager.calls)
        self.assertEqual([job.state for job in manager.snapshot()], ["running", "metadata", "queued"])

    def test_enter_lists_the_rows_actions(self):
        manager = install(self, FakeManager(sample_jobs()))
        with driving([K.ENTER, K.ENTER, K.ESC]):  # Enter on the running row, Enter on Stop, Esc out
            downloads_ui.downloads_screen()
        self.assertIn(("stop", "job1"), manager.calls)
        seen = capture(None, downloads_ui, lambda: downloads_ui._actions(manager, manager.job("job7")))
        self.assertEqual([plain(item.label) for item in seen["items"]],
                         ["Resume", "Open folder", "Remove from the list", "Show log", "Back"])
        seen = capture(None, downloads_ui, lambda: downloads_ui._actions(manager, manager.job("job6")))
        self.assertEqual(plain(seen["items"][0].label), "Retry")
        with patch.object(downloads_ui, "arrow_select", return_value=0):
            downloads_ui._actions(manager, manager.job("job7"))  # Resume
        enqueued = [call for call in manager.calls if call[0] == "enqueue"]
        self.assertEqual(enqueued[-1][1], "One Piece 1090 (1080p)")
        self.assertIn(("remove", "job7"), manager.calls)  # the stopped row makes way for the resumed one

    def test_an_empty_screen_says_how_to_start(self):
        install(self, None)
        seen = capture(None, downloads_ui, downloads_ui.downloads_screen)
        self.assertEqual([plain(item.label) for item in seen["items"]], ["Back"])
        intro = " ".join(line.plain for line in seen["kwargs"]["intro"]())
        self.assertIn("Nothing is downloading in the background.", intro)
        self.assertIn("Downloads run: in background", intro)

    # --- entry points and keys ------------------------------------------------------------------

    def test_the_main_menu_gains_the_row_and_d_once_a_download_started(self):
        install(self, None)
        seen = capture(None, prompts, prompts.provider_select_prompt)
        self.assertNotIn("__downloads__", [item.value for item in seen["items"]])
        self.assertNotIn("d", seen["kwargs"]["hotkeys"])
        self.assertNotIn("D downloads", seen["kwargs"]["footer"]())
        manager = install(self, FakeManager(sample_jobs()))
        seen = capture(None, prompts, prompts.provider_select_prompt)
        row = next(item for item in seen["items"] if item.value == "__downloads__")
        values = [item.value for item in seen["items"]]
        self.assertEqual(values[values.index("__downloads__") + 1], "__settings__")
        self.assertEqual(plain(row.hint), "2 running · 1 queued  D")
        self.assertEqual(seen["kwargs"]["hotkeys"]["d"], "downloads")
        self.assertIn("D downloads", seen["kwargs"]["footer"]())
        manager.set_state("job1", "done")
        self.assertTrue(seen["kwargs"]["refresh"]())
        self.assertEqual(plain(row.hint), "1 running · 1 queued  D")

    def test_d_opens_downloads_from_the_main_menu_and_whats_next(self):
        install(self, FakeManager(sample_jobs()))
        opened = []
        with patch.object(downloads_ui, "downloads_screen", side_effect=lambda **kw: opened.append("menu")), \
             driving(["d", K.ESC]):
            self.assertIsNone(prompts.provider_select_prompt())
        with patch.object(downloads_ui, "downloads_screen", side_effect=lambda **kw: opened.append("next")), \
             driving(["D", "q"]):
            self.assertEqual(prompts.search_again_prompt(), "exit")
        self.assertEqual(opened, ["menu", "next"])

    def test_the_d_keys_collide_with_nothing(self):
        install(self, FakeManager(sample_jobs()))
        seen = capture(None, prompts, prompts.provider_select_prompt)
        hotkeys = seen["kwargs"]["hotkeys"]
        self.assertEqual({key: value for key, value in hotkeys.items() if key.lower() == "d"},
                         {"D": "downloads", "d": "downloads"})
        self.assertNotIn("d", seen["kwargs"]["key_actions"])
        seen = capture(None, prompts, prompts.search_again_prompt)
        self.assertEqual(seen["kwargs"]["hotkeys"]["d"], "downloads")
        self.assertEqual([item.hint for item in seen["items"]].count("D"), 1)
        install(self, None)
        seen = capture(None, prompts, prompts.search_again_prompt)
        self.assertNotIn("d", seen["kwargs"]["hotkeys"])
        seen = capture(None, prompts, prompts.quick_actions_menu)
        items, actions = seen["items"], seen["kwargs"]["key_actions"]
        self.assertEqual(items[actions["d"](0, items)].value, "discover")  # D stays Discover here
        self.assertEqual(items[actions["g"](0, items)].value, "downloads")

    # --- the setting and the enqueue paths ------------------------------------------------------

    def test_the_download_menu_toggles_the_saved_setting(self):
        self.assertFalse(main._background_on())
        seen = capture(None, prompts, lambda: prompts.download_method_prompt(magnet="magnet:?xt=urn:btih:" + "ab" * 20))
        items = seen["items"]
        index = next(i for i, item in enumerate(items) if item.value == "toggle_background")
        self.assertEqual(items[index - 1].value, "toggle_quiet")
        self.assertEqual(items[index].label, "Downloads run: in this screen")
        self.assertTrue(seen["kwargs"]["on_action"](index, items))
        self.assertEqual(items[index].label, "Downloads run: in background")
        self.assertTrue(state.load_setting("background_downloads"))
        self.assertTrue(main._background_on())

    def session(self, name="Example", magnet="magnet:?xt=urn:btih:" + "ff" * 20, indexes=None):
        return SimpleNamespace(result={"name": name, "source": "Nyaa", "size": 1_500_000_000, "seeders": 12},
                               magnet=magnet, download_indexes=indexes)

    def test_a_single_download_is_enqueued_then_confirmed(self):
        manager = install(self, FakeManager(sample_jobs()))
        provider = SimpleNamespace(slug="anime")
        with patch.object(downloads_ui, "background_started_prompt", return_value="next") as prompt:
            self.assertEqual(main._background_single(self.session(indexes=[1, 2]), provider), "next")
        self.assertEqual([call for call in manager.calls if call[0] == "enqueue"][-1],
                         ("enqueue", "Example", "magnet:?xt=urn:btih:" + "ff" * 20, [1, 2], "Nyaa", "anime", "aria", None))
        self.assertEqual(prompt.call_args.args, ("Example", "D:\\Torrents\\Anime"))
        self.assertEqual(prompt.call_args.kwargs, {"size_bytes": 1_500_000_000, "ahead": 3})

    def test_a_duplicate_is_said_plainly_and_the_options_stay_open(self):
        install(self, FakeManager(sample_jobs()))
        provider = SimpleNamespace(slug="anime")
        with patch.object(downloads_ui, "background_started_prompt", return_value="back"):
            self.assertEqual(main._background_single(self.session(magnet=sample_jobs()[0].magnet), provider), "back")
        self.assertIn("already downloading", chrome.take_message())

    def test_a_batch_is_enrolled_as_one_group(self):
        manager = install(self, FakeManager())
        provider = SimpleNamespace(slug="movies")
        picked = [{"name": "One", "source": "Apibay"}, {"name": "Two", "source": "Apibay"}]
        magnets = ["magnet:?xt=urn:btih:" + "01" * 20, "magnet:?xt=urn:btih:" + "02" * 20]
        with patch.object(main, "provider_for_result", return_value=provider), \
             patch.object(downloads_ui, "background_started_prompt", return_value="next") as prompt:
            self.assertEqual(main._batch_background(provider, picked, magnets, skipped=1), "next")
        enqueued = [call for call in manager.calls if call[0] == "enqueue"]
        self.assertEqual([call[1] for call in enqueued], ["One", "Two"])
        self.assertEqual(len({call[7] for call in enqueued}), 1)  # one group
        self.assertIn(("batch",), manager.calls)
        self.assertEqual(prompt.call_args.args[0], "2 torrents queued")
        self.assertEqual(prompt.call_args.kwargs["facts"], ["1 skipped (no magnet)"])

    def test_the_confirmation_offers_continue_back_and_downloads(self):
        install(self, FakeManager(sample_jobs()))
        with driving([K.ENTER]):
            self.assertEqual(downloads_ui.background_started_prompt(FRIEREN, "D:\\Torrents\\Anime", ahead=2), "next")
        with driving([K.ESC]):
            self.assertEqual(downloads_ui.background_started_prompt(FRIEREN, "D:\\Torrents\\Anime"), "back")
        with driving(["d", K.ESC]), patch.object(downloads_ui, "downloads_screen") as screen:
            self.assertEqual(downloads_ui.background_started_prompt(FRIEREN, "D:\\Torrents\\Anime"), "back")
        screen.assert_called_once()
        seen = capture(None, downloads_ui, lambda: downloads_ui.background_started_prompt(
            FRIEREN, "D:\\Torrents\\Anime", size_bytes=1_503_238_553, ahead=2))
        self.assertEqual([line.plain for line in seen["kwargs"]["intro"]],
                         [FRIEREN, "1.4 GB · queued behind 2 running · saves to D:\\Torrents\\Anime"])

    # --- quitting and updating ------------------------------------------------------------------

    def test_the_quit_prompt_keeps_the_app_open_unless_told_to_stop(self):
        install(self, FakeManager(sample_jobs()))
        for keys in ([K.ESC], ["\x03"], [K.ENTER]):
            with self.subTest(keys=keys), driving(keys):
                self.assertFalse(downloads_ui.quit_prompt())
        with driving([K.DOWN, K.ENTER]):
            self.assertTrue(downloads_ui.quit_prompt())
        seen = capture(None, downloads_ui, downloads_ui.quit_prompt)
        self.assertEqual([plain(item.label) for item in seen["items"]],
                         ["Keep Torrent Finder open", "Stop 3 downloads and quit"])
        self.assertEqual(seen["kwargs"]["intro"][0].plain, "3 downloads are running:")

    def test_every_exit_asks_the_same_question_and_stop_shuts_the_engine_down(self):
        manager = install(self, FakeManager(sample_jobs()))
        with patch.object(downloads_ui, "quit_prompt", return_value=False):
            self.assertFalse(main._confirm_quit())
            self.assertFalse(main._confirm_quit(guarded=True))
        self.assertNotIn(("shutdown", True), manager.calls)
        with patch.object(downloads_ui, "quit_prompt", return_value=True), patch.object(main, "console"):
            self.assertTrue(main._confirm_quit(guarded=True))
        self.assertIn(("shutdown", True), manager.calls)
        with patch.object(prompts, "confirm_prompt", return_value=True) as confirm:
            self.assertTrue(main._confirm_quit())  # nothing runs any more: the plain confirmation
        confirm.assert_called_once()
        with patch.object(prompts, "confirm_prompt") as confirm:
            self.assertTrue(main._confirm_quit(guarded=True))
        confirm.assert_not_called()

    def test_updates_wait_while_downloads_run(self):
        install(self, FakeManager(sample_jobs()))
        with patch.object(main, "run_update") as run, patch.object(main, "clear_screen"):
            self.assertFalse(main._run_update_flow({"kind": "pip", "current": "1", "latest": "2"}))
        run.assert_not_called()
        self.assertIn("The update waits: 3 downloads are running.", chrome.take_message())

    def test_main_shuts_the_engine_down_on_the_way_out(self):
        manager = install(self, FakeManager(sample_jobs()))
        downloads.shutdown_all()
        self.assertIn(("shutdown", True), manager.calls)
        self.assertFalse(downloads.busy())

    # --- the completion notice ------------------------------------------------------------------

    def test_a_finished_download_announces_itself_once(self):
        install(self, FakeManager([job for job in sample_jobs() if job.id in ("job4", "job6")]))
        watched = downloads_ui.watch()
        messages = [chrome.take_message(), chrome.take_message()]
        self.assertIn("[good]✓[/good] [SubsPlease] Frieren - 02 (1080p) finished · 1.4 GB · D opens Downloads", messages[0])
        self.assertIn("[bad]✗[/bad] Blue Giant 2023 1080p failed · D opens Downloads", messages[1])
        self.assertFalse(downloads_ui.poll(watched))
        self.assertEqual(chrome.take_message(), "")

    def test_a_menu_shows_the_notice_when_a_download_finishes_under_it(self):
        manager = install(self, FakeManager([sample_jobs()[0]]))
        theme.apply("citrinitas", focus="bar", density="comfortable")
        watched = downloads_ui.watch()
        manager.set_state("job1", "done", done_bytes=int(1.4 * GIB), total_bytes=int(1.4 * GIB))
        self.assertTrue(downloads_ui.poll(watched))
        message = chrome.take_message()
        self.assertIn(FRIEREN + " finished · 1.4 GB · D opens Downloads", message)
        screen = Console(file=io.StringIO(), width=137, height=36, color_system=None)
        with patch.object(selector, "console", screen):
            screen.print(selector._build_panel([SelectItem("Row", "row")], 0, "Menu", False, message=message))
        self.assertIn("✓ " + FRIEREN + " finished", screen.file.getvalue().splitlines()[0])


if __name__ == "__main__":
    unittest.main()
