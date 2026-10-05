import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from torrent_finder.ui import prompts
from torrent_finder.ui.selector import _next_enabled


class DownloadMethodMenuTests(unittest.TestCase):
    def test_uninstalled_methods_remain_navigable_and_show_install_links(self):
        captured = {}

        def capture_menu(items, **_kwargs):
            captured["items"] = items
            return next(index for index, item in enumerate(items) if item.value == "back")

        with patch.object(prompts, "has_aria2", return_value=False), \
             patch.object(prompts, "has_webtorrent", return_value=False), \
             patch.object(prompts, "has_peerflix", return_value=False), \
             patch.object(prompts, "detect_torrent_client", return_value="torrent client"), \
             patch.object(prompts, "arrow_select", side_effect=capture_menu), \
             patch("torrent_finder.state.load_setting", return_value=False):
            result = prompts.download_method_prompt(
                show_subtitles=False,
                show_streaming=True,
                show_episode_picker=True,
            )

        self.assertEqual(result, "back")
        items = captured["items"]
        by_value = {item.value: item for item in items}
        install_links = {
            "aria": "https://aria2.github.io/",
            "d": "https://www.npmjs.com/package/webtorrent-cli",
            "p": "https://www.npmjs.com/package/peerflix",
            "stream_w": "https://www.npmjs.com/package/webtorrent-cli",
            "stream_p": "https://www.npmjs.com/package/peerflix",
            "pick_episodes": "https://aria2.github.io/",
        }

        for value, link in install_links.items():
            with self.subTest(value=value):
                self.assertTrue(by_value[value].enabled)
                self.assertTrue(by_value[value].passive)
                self.assertTrue(by_value[value].hint.startswith("install: "))  # short enough to sit inline
                self.assertIn(link, by_value[value].description)  # the full link when focused

        open_index = next(index for index, item in enumerate(items) if item.value == "t")
        aria_index = next(index for index, item in enumerate(items) if item.value == "aria")
        self.assertEqual(_next_enabled(items, open_index, 1), aria_index)
        self.assertEqual(by_value["aria"].label.style, prompts.theme.MUTED)  # an unavailable tool reads quieter


class DownloadSummaryTests(unittest.TestCase):
    def test_the_summary_says_what_the_torrent_is(self):
        torrent = {"name": "Frieren - 01", "source": "Nyaa", "size": 1_450_000_000, "seeders": 812,
                   "leechers": 140, "uploaded_at": 1_789_000_000}
        summary = prompts.torrent_summary(torrent, file_count=12, subtitles="auto-detect from torrent",
                                          selected=[1, 2, 3, 7])
        self.assertEqual(summary.plain, "Nyaa · 1.4 GB · 812 seeds · 140 leeches · 2026-09-10 · 12 files"
                                        " · 4 picked (1-3,7) · subs auto")
        seeds = next(span for span in summary.spans if summary.plain[span.start:span.end] == "812")
        self.assertEqual(str(seeds.style), prompts.theme.seed_style(812))
        self.assertEqual(prompts.torrent_summary({"seeders": 0}, subtitles="disabled").plain,
                         "0 seeds · 0 leeches · subs off")

    def test_the_client_row_is_marked_recommended(self):
        captured = {}
        with patch.object(prompts, "detect_torrent_client", return_value="qBittorrent"), \
             patch.object(prompts, "arrow_select", side_effect=lambda items, **kw: captured.update(kw, items=items)), \
             patch("torrent_finder.state.load_setting", return_value=False):
            prompts.download_method_prompt(show_subtitles=False, show_streaming=False)
        client = next(item for item in captured["items"] if item.value == "t")
        self.assertTrue(client.hint.plain.startswith("recommended"))
        self.assertEqual(captured["start_index"], captured["items"].index(client))


if __name__ == "__main__":
    unittest.main()
