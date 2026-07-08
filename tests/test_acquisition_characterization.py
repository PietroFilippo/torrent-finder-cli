import importlib
import os
import tempfile
import unittest
from unittest.mock import patch


class MagnetForContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        from torrent_finder import store

        store.STATE_PATH = os.path.join(cls._tmp.name, "filter_state.json")
        store._cache = None
        store._dirty = False
        cls.main = importlib.import_module("torrent_finder.main")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_magnet_for_direct_hash_result_builds_magnet(self):
        magnet = self.main._magnet_for(
            {
                "name": "Direct Result",
                "info_hash": "a" * 40,
                "source": "Apibay",
            }
        )

        self.assertIsNotNone(magnet)
        self.assertTrue(magnet.startswith("magnet:?xt=urn:btih:" + "a" * 40))
        self.assertIn("&dn=Direct Result&", magnet)

    def test_magnet_for_non_magnet_sources_returns_none(self):
        self.assertIsNone(
            self.main._magnet_for({"name": "Online", "source": "Online-Fix"})
        )
        self.assertIsNone(
            self.main._magnet_for({"name": "Manga", "source": "Madokami"})
        )

    def test_magnet_for_rutracker_resolves_lazy_hash_from_topic_id(self):
        resolved = "b" * 40
        with patch("torrent_finder.rutracker.resolve_info_hash", return_value=resolved) as resolve:
            magnet = self.main._magnet_for(
                {
                    "name": "Ru Result",
                    "info_hash": "123",
                    "source": "RuTracker",
                    "rt_topic_id": "987",
                }
            )

        resolve.assert_called_once_with("987")
        self.assertTrue(magnet.startswith("magnet:?xt=urn:btih:" + resolved))
        self.assertIn("&dn=Ru Result&", magnet)

    def test_magnet_for_fitgirl_resolves_lazy_hash_from_post_url(self):
        resolved = "c" * 40
        with patch("torrent_finder.fitgirl.resolve_info_hash", return_value=resolved) as resolve:
            magnet = self.main._magnet_for(
                {
                    "name": "FitGirl Result",
                    "info_hash": "fitgirl-1",
                    "source": "FitGirl",
                    "fg_post_url": "https://fitgirl.example/post",
                }
            )

        resolve.assert_called_once_with("https://fitgirl.example/post")
        self.assertTrue(magnet.startswith("magnet:?xt=urn:btih:" + resolved))
        self.assertIn("&dn=FitGirl Result&", magnet)


if __name__ == "__main__":
    unittest.main()
