import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

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
                self.assertIn(link, by_value[value].hint)

        open_index = next(index for index, item in enumerate(items) if item.value == "t")
        aria_index = next(index for index, item in enumerate(items) if item.value == "aria")
        self.assertEqual(_next_enabled(items, open_index, 1), aria_index)


if __name__ == "__main__":
    unittest.main()
