import io
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rich.console import Console

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from torrent_finder import acquisition, main
from torrent_finder.torrent_session import TorrentSession
from torrent_finder.ui import prompts, selector
from isolation import isolate_store


class DownloadNavigationTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)
        self.provider = SimpleNamespace(slug="anime", result_sort="relevance",
                                        filter_summary=lambda: "No filters")
        self.result = {"name": "Example", "source": "Nyaa", "info_hash": "a" * 40}
        self.magnet = "magnet:?xt=urn:btih:" + "a" * 40
        self.session = TorrentSession(self.result, self.magnet)
        self.session.set_selected_files([1, 3])
        self.session.set_sub_choice({"mode": "external", "paths": ["example.srt"]})
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("clear_screen", "record_torrent_picked", "record_method_pick",
                     "record_method_complete", "record_magnet_dispatch"):
            self.stack.enter_context(patch.object(main, name))
        self.stack.enter_context(patch.object(main, "console", Console(file=io.StringIO())))
        self.stack.enter_context(patch("torrent_finder.qbittorrent.configured", return_value=False))

    def run_single(self, method, after="back", accepted=True):
        adapter = Mock(style="magnet-direct")
        adapter.pick.return_value = acquisition.PickOutcome("menu", self.magnet)
        with patch.object(main.acquisition, "for_result", return_value=adapter), \
             patch.object(main, "TorrentSession", return_value=self.session) as session, \
             patch.object(main, "interactive_select", return_value=("one", 0)) as results, \
             patch.object(main, "download_method_prompt", side_effect=[method, "cancel"]) as choices, \
             patch.object(main, "download_complete_prompt", return_value=after) as finished, \
             patch.object(main, "open_magnet") as desktop, \
             patch("torrent_finder.ui.qbittorrent.send_results", return_value=accepted) as webui, \
             patch.object(main, "download_with_aria2", return_value=True) as aria, \
             patch.object(main, "download_with_peerflix", return_value=True) as peerflix, \
             patch.object(main, "download_with_webtorrent", return_value=True) as webtorrent:
            self.assertEqual(main.browse_results(self.provider, [self.result]), "next")
        results.assert_called_once()
        session.assert_called_once()
        adapter.pick.assert_called_once()
        calls = {"t": desktop, "qbittorrent": webui, "aria": aria, "p": peerflix, "d": webtorrent}
        calls[method].assert_called_once()
        if method == "qbittorrent" and not accepted:
            finished.assert_not_called()
        else:
            finished.assert_called_once()
        return choices

    def test_back_keeps_torrent_file_and_subtitle_choices_without_resubmitting(self):
        for method in ("t", "qbittorrent", "aria", "p", "d"):
            with self.subTest(method=method):
                choices = self.run_single(method)
                self.assertEqual(choices.call_count, 2)
                for call in choices.call_args_list:
                    self.assertEqual(call.kwargs["magnet"], self.magnet)
                    self.assertEqual(call.kwargs["selected_indexes"], [1, 3])
                    self.assertEqual(call.kwargs["sub_choice"], self.session.sub_choice)

    def test_continue_leaves_download_choices(self):
        for method in ("t", "qbittorrent"):
            with self.subTest(method=method):
                self.assertEqual(self.run_single(method, after="next").call_count, 1)

    def test_unsent_webui_returns_directly_to_download_choices(self):
        self.assertEqual(self.run_single("qbittorrent", accepted=False).call_count, 2)

    def test_batch_back_keeps_selection_without_resubmitting(self):
        rows = [self.result, dict(self.result, info_hash="b" * 40)]
        for action, target in (("open", "_batch_handoff"), ("aria", "_batch_aria2"),
                               ("qbittorrent", None)):
            with self.subTest(action=action), ExitStack() as stack:
                menu = stack.enter_context(patch.object(prompts, "batch_download_menu", side_effect=[action, "back"]))
                stack.enter_context(patch.object(main, "download_complete_prompt", return_value="back"))
                if target:
                    send = stack.enter_context(patch.object(main, target, return_value="back"))
                else:
                    send = stack.enter_context(patch("torrent_finder.ui.qbittorrent.send_results", return_value=True))
                self.assertEqual(main._batch_flow(self.provider, rows, [0, 1]), "back")
                self.assertEqual(menu.call_count, 2)
                self.assertEqual(menu.call_args_list[0], menu.call_args_list[1])
                send.assert_called_once()
                if target:
                    send.assert_called_with(self.provider, rows, [0, 1])
                else:
                    send.assert_called_with(rows)

    def test_torrent_file_webui_back_returns_to_client_choices(self):
        adapter = Mock(style="torrent-file-handoff")
        with patch("torrent_finder.qbittorrent.configured", return_value=True), \
             patch.object(main.acquisition, "for_result", return_value=adapter), \
             patch.object(main, "interactive_select", side_effect=[("one", 0), None]), \
             patch.object(selector, "arrow_select", side_effect=[0, None]) as choices, \
             patch("torrent_finder.ui.qbittorrent.send_results", return_value=True) as send, \
             patch.object(main, "download_complete_prompt", return_value="back"):
            self.assertEqual(main.browse_results(self.provider, [self.result]), "back")
        self.assertEqual(choices.call_count, 2)
        send.assert_called_once_with([self.result])
        adapter.pick.assert_not_called()

    def test_completion_menu_supports_enter_back_escape_and_ctrl_c(self):
        for keys, expected in ((["\r"], "next"), ([selector.readchar.key.DOWN, "\r"], "back"),
                               ([selector.readchar.key.ESC], "back"), ([KeyboardInterrupt], "back")):
            with self.subTest(keys=keys), \
                 patch.object(selector, "console", Console(file=io.StringIO(), width=40, height=16)), \
                 patch.object(selector.sys, "stdout", io.StringIO()), \
                 patch.object(selector.readchar, "readkey", side_effect=keys):
                self.assertEqual(prompts.download_complete_prompt(), expected)


if __name__ == "__main__":
    unittest.main()
