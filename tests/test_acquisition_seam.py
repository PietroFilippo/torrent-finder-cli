"""Contract tests for the acquisition seam (torrent_finder.acquisition).

Headless: every site call and client handoff is mocked; only the adapter
logic runs. The magnet contract itself is pinned by
test_acquisition_characterization.py through main._magnet_for.
"""

import threading
import unittest
from unittest.mock import patch

from torrent_finder import acquisition
from torrent_finder.search_result import SearchResult


def _noop_status(_suffix: str) -> None:
    pass


class RegistryTests(unittest.TestCase):
    def test_styles_by_source(self):
        expect = {
            "Apibay": "magnet-direct",
            "SolidTorrents": "magnet-direct",
            "Nyaa": "magnet-direct",
            "YTS": "magnet-direct",
            "RuTracker": "magnet-lazy-resolve",
            "FitGirl": "magnet-lazy-resolve",
            "Online-Fix": "torrent-file-handoff",
            "Madokami": "direct-download",
        }
        for source, style in expect.items():
            self.assertEqual(acquisition.for_result({"source": source}).style, style)

    def test_unknown_source_defaults_to_magnet_direct(self):
        self.assertEqual(acquisition.for_result({}).style, "magnet-direct")
        self.assertEqual(acquisition.for_result({"source": "Brand-New"}).style, "magnet-direct")

    def test_has_magnet_flags(self):
        self.assertTrue(acquisition.for_result({"source": "Apibay"}).has_magnet)
        self.assertTrue(acquisition.for_result({"source": "RuTracker"}).has_magnet)
        self.assertFalse(acquisition.for_result({"source": "Online-Fix"}).has_magnet)
        self.assertFalse(acquisition.for_result({"source": "Madokami"}).has_magnet)


class BatchItemTests(unittest.TestCase):
    def setUp(self):
        self.cancel = threading.Event()

    def _batch(self, result, **extra):
        return acquisition.for_result(result).batch_item(
            result, download_dir="D:/dl", cancel_event=self.cancel,
            set_status=extra.pop("set_status", _noop_status),
        )

    def test_magnet_direct_opens_magnet(self):
        with patch("torrent_finder.downloader.open_magnet") as om:
            out = self._batch({"name": "X", "info_hash": "b" * 40, "source": "Apibay"})
        self.assertTrue(out.ok)
        self.assertFalse(out.saved_direct)
        om.assert_called_once()

    def test_magnet_direct_without_hash_fails(self):
        with patch("torrent_finder.downloader.open_magnet") as om:
            out = self._batch({"name": "X", "info_hash": "", "source": "Apibay"})
        self.assertFalse(out.ok)
        om.assert_not_called()

    def test_online_fix_success_surfaces_archive_password(self):
        with patch("torrent_finder.online_fix.fetch_torrent_for", return_value="C:/t.torrent"), \
             patch("torrent_finder.downloader.open_torrent_file", return_value=True):
            out = self._batch({"name": "G", "source": "Online-Fix", "of_post_url": "https://of/p"})
        self.assertTrue(out.ok)
        self.assertTrue(out.password)

    def test_online_fix_failure_lands_in_manual_list(self):
        with patch("torrent_finder.online_fix.fetch_torrent_for", return_value=None):
            out = self._batch({"name": "G", "source": "Online-Fix", "page_url": "https://of/p"})
        self.assertFalse(out.ok)
        self.assertEqual(out.manual_url, "https://of/p")

    def test_madokami_file_downloads_direct_with_mb_counter(self):
        seen: list[str] = []

        def fake_dl(path, dest, cancel_event=None, progress_cb=None):
            progress_cb(1048576, 2097152)
            return "C:/dl/v.zip"

        with patch("torrent_finder.madokami.is_file_path", return_value=True), \
             patch("torrent_finder.madokami.download_file", side_effect=fake_dl):
            out = self._batch(
                SearchResult(name="M", source="Madokami", handle={"mdk_path": "/x/f.zip"}),
                set_status=seen.append,
            )
        self.assertTrue(out.ok)
        self.assertTrue(out.saved_direct)
        self.assertEqual(seen, ["1.0/2.0 MB"])

    def test_madokami_folder_cannot_batch_goes_manual(self):
        with patch("torrent_finder.madokami.is_file_path", return_value=False):
            out = self._batch(
                {"name": "M", "source": "Madokami", "mdk_path": "/x/", "page_url": "https://mdk/x"}
            )
        self.assertFalse(out.ok)
        self.assertEqual(out.manual_url, "https://mdk/x")


class PickTests(unittest.TestCase):
    def test_magnet_direct_pick_goes_to_menu(self):
        out = acquisition.for_result({"source": "Apibay"}).pick(
            {"name": "X", "info_hash": "e" * 40, "source": "Apibay"}
        )
        self.assertEqual(out.action, "menu")
        self.assertIn("e" * 40, out.magnet)

    def test_lazy_pick_persists_resolved_hash_on_result(self):
        r = SearchResult(name="Ru", info_hash="123", source="RuTracker",
                         handle={"rt_topic_id": "9"})
        with patch("torrent_finder.rutracker.resolve_info_hash", return_value="d" * 40):
            out = acquisition.for_result(r).pick(r)
        self.assertEqual(out.action, "menu")
        self.assertIn("d" * 40, out.magnet)
        self.assertEqual(r.info_hash, "d" * 40)


if __name__ == "__main__":
    unittest.main()
