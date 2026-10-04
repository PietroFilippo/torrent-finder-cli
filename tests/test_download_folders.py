"""Downloads land together and, on request, as pages (user report, 2026-10-04).

Picking several Madokami chapters saved each archive loose in the download
folder, among unrelated files. They now share a folder named after the series,
and the "Unpack page archives" setting turns each manga archive into a folder
of pages, for Madokami files and for torrents downloaded in the app.
"""

import io
import os
import subprocess
import tempfile
import threading
import unittest
import zipfile
from unittest.mock import patch

from rich.console import Console

import isolation  # noqa: F401  (keeps the user's settings out of reach)
from isolation import isolate_store
from torrent_finder import acquisition, madokami, main, unpack
from torrent_finder.search_result import SearchResult
from torrent_finder.state import load_setting, save_setting
from torrent_finder.torrent_meta import TorrentFile, TorrentMetadata

NAKI = "/Manga/N/NA/NAKI/Naki no Ryuu"


class FolderTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = directory.name
        screen = Console(file=io.StringIO(), width=100)  # panels and spinners stay off the real terminal
        for module in (acquisition, main):
            patcher = patch.object(module, "console", screen)
            patcher.start()
            self.addCleanup(patcher.stop)

    def path(self, *parts):
        return os.path.join(self.folder, *parts)

    def make_zip(self, name, members, folder=None):
        path = os.path.join(folder or self.folder, name)
        with zipfile.ZipFile(path, "w") as archive:
            for member in members:
                archive.writestr(member, b"page")
        return path

    def tree(self, *parts):
        root = self.path(*parts)
        return sorted(os.path.relpath(os.path.join(here, name), root).replace(os.sep, "/")
                      for here, _folders, files in os.walk(root) for name in files)


class UnpackTests(FolderTestCase):
    def test_pages_go_to_a_folder_named_after_the_archive(self):
        archive = self.make_zip("Naki no Ryuu - v1 c2 [batoto].zip",
                                ["001.jpg", "002.png", "ComicInfo.xml", "__MACOSX/._001.jpg"])
        folder, problem = unpack.unpack(archive)
        self.assertEqual((folder, problem), (self.path("Naki no Ryuu - v1 c2 [batoto]"), ""))
        self.assertEqual(self.tree("Naki no Ryuu - v1 c2 [batoto]"), ["001.jpg", "002.png", "ComicInfo.xml"])
        self.assertFalse(os.path.exists(archive))
        self.assertEqual(os.listdir(self.folder), ["Naki no Ryuu - v1 c2 [batoto]"])  # no scratch left

    def test_one_folder_inside_the_archive_is_not_repeated(self):
        archive = self.make_zip("c03.cbz", ["Chapter 3/001.jpg", "Chapter 3/sub/002.jpg"])
        unpack.unpack(archive)
        self.assertEqual(self.tree("c03"), ["001.jpg", "sub/002.jpg"])

    def test_an_existing_folder_is_never_merged_into(self):
        os.mkdir(self.path("v01"))
        folder, _ = unpack.unpack(self.make_zip("v01.zip", ["001.jpg"]))
        self.assertEqual(folder, self.path("v01 (1)"))
        self.assertEqual(os.listdir(self.path("v01")), [])

    def test_archives_that_are_not_only_pages_are_left_alone(self):
        for members in (["setup.exe", "001.jpg"], ["readme.txt"], ["book.pdf"]):
            with self.subTest(members=members):
                archive = self.make_zip("game.zip", members)
                self.assertEqual(unpack.unpack(archive, expect_pages=True), (None, ""))
                self.assertTrue(os.path.exists(archive))
                os.remove(archive)

    def test_a_failure_keeps_the_archive_and_leaves_no_scratch(self):
        archive = self.make_zip("v02.cbz", ["001.jpg"])
        with patch.object(unpack._ZipReader, "extract", side_effect=OSError("disk full")):
            folder, problem = unpack.unpack(archive)
        self.assertIsNone(folder)
        self.assertIn("disk full", problem)
        self.assertEqual(os.listdir(self.folder), ["v02.cbz"])

    def test_rar_without_a_program_is_reported_only_where_pages_are_expected(self):
        for name, expect_pages, reported in (("c01.rar", True, True), ("c01.cbr", False, True),
                                             ("game.rar", False, False)):
            with self.subTest(name=name, expect_pages=expect_pages):
                path = self.path(name)
                with open(path, "wb") as handle:
                    handle.write(b"Rar!\x1a\x07\x00")
                with patch.object(unpack, "_tools", return_value=[]):
                    folder, problem = unpack.unpack(path, expect_pages=expect_pages)
                self.assertIsNone(folder)
                self.assertEqual(bool(problem), reported)
                if reported:
                    self.assertIn("7-Zip", problem)
                self.assertTrue(os.path.exists(path))

    def test_page_lists_from_every_program(self):
        self.assertTrue(unpack._is_pages(["Chapter 1\\001.jpg", "Chapter 1\\002.png", "Chapter 1"]))  # UnRAR
        self.assertTrue(unpack._is_pages(["Chapter 1/001.jpg", "Chapter 1/"]))  # bsdtar on zip/7z
        self.assertTrue(unpack._is_pages([".DS_Store", "001.webp", "Thumbs.db", "__MACOSX/Chapter 1/Icon"]))
        self.assertFalse(unpack._is_pages(["Chapter 1/"]))  # no pages at all
        self.assertFalse(unpack._is_pages(["001.jpg", "inner.cbz"]))  # archives inside: leave it whole

    def test_unrar_is_asked_only_about_rar(self):
        path = self.path("c01.7z")
        with open(path, "wb") as handle:
            handle.write(b"7z")
        with patch.object(unpack, "_tools", return_value=[("unrar", "unrar")]), \
             patch.object(unpack, "_run") as run:
            self.assertEqual(unpack.unpack(path, expect_pages=True)[0], None)
        run.assert_not_called()

    def test_split_rar_volumes_are_not_archives_on_their_own(self):
        self.assertFalse(unpack.is_archive("Game.part2.rar"))
        self.assertTrue(unpack.is_archive("Naki no Ryuu Chapter 1.RAR"))
        self.assertFalse(unpack.is_archive("v01.pdf"))

    @unittest.skipUnless(any(kind == "bsdtar" for kind, _exe in unpack._tools()), "needs bsdtar")
    def test_a_7z_page_archive_unpacks_with_the_system_tar(self):
        tar = next(exe for kind, exe in unpack._tools() if kind == "bsdtar")
        os.makedirs(self.path("src", "c05"))
        for page in ("001.jpg", "002.jpg"):
            with open(self.path("src", "c05", page), "wb") as handle:
                handle.write(b"page")
        archive = self.path("c05.cb7")
        subprocess.run([tar, "-cf", archive, "--format", "7zip", "-C", self.path("src"), "c05"], check=True)
        self.assertFalse(zipfile.is_zipfile(archive))
        folder, problem = unpack.unpack(archive)
        self.assertEqual((folder, problem), (self.path("c05"), ""))
        self.assertEqual(self.tree("c05"), ["001.jpg", "002.jpg"])


class TorrentFilesTests(FolderTestCase):
    def touch(self, *parts):
        os.makedirs(self.path(*parts[:-1]), exist_ok=True)
        with open(self.path(*parts), "wb") as handle:
            handle.write(b"x")
        return self.path(*parts)

    def test_the_selected_files_of_a_multi_file_torrent(self):
        first = self.touch("Naki no Ryuu", "v01.cbz")
        self.touch("Naki no Ryuu", "v02.cbz")
        meta = TorrentMetadata("Naki no Ryuu", [TorrentFile(1, "v01.cbz", 1), TorrentFile(2, "v02.cbz", 1)])
        self.assertEqual(unpack.torrent_files(self.folder, meta, [1]), [first])

    def test_a_single_file_torrent_is_saved_under_its_name(self):
        path = self.touch("Naki no Ryuu v01.cbz")
        meta = TorrentMetadata("Naki no Ryuu v01.cbz", [TorrentFile(1, "Naki no Ryuu v01.cbz", 1)])
        self.assertEqual(unpack.torrent_files(self.folder, meta), [path])

    def test_a_loose_file_with_the_same_name_is_not_the_torrent_s(self):
        self.touch("v01.cbz")  # from an earlier download
        meta = TorrentMetadata("Naki no Ryuu", [TorrentFile(1, "v01.cbz", 1), TorrentFile(2, "v02.cbz", 1)])
        self.assertEqual(unpack.torrent_files(self.folder, meta), [])

    def test_without_a_file_list_the_magnet_name_is_used(self):
        path = self.touch("Naki no Ryuu", "Vol 1", "c01.zip")
        magnet = "magnet:?xt=urn:btih:" + "a" * 40 + "&dn=Naki+no+Ryuu"
        self.assertEqual(unpack.torrent_files(self.folder, magnet=magnet), [path])

    def test_a_linked_torrent_folder_is_not_followed_outside(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        with open(os.path.join(outside.name, "c01.zip"), "wb") as handle:
            handle.write(b"x")
        try:
            os.symlink(outside.name, self.path("Naki no Ryuu"), target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links aren't allowed here")
        self.assertEqual(unpack.torrent_files(self.folder, magnet="magnet:?dn=Naki+no+Ryuu"), [])

    def test_names_never_reach_outside_the_download_folder(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        with open(os.path.join(outside.name, "c01.zip"), "wb") as handle:
            handle.write(b"x")
        escape = os.path.relpath(outside.name, self.folder)
        meta = TorrentMetadata(escape, [TorrentFile(1, "c01.zip", 1), TorrentFile(2, "c02.zip", 1)])
        self.assertEqual(unpack.torrent_files(self.folder, meta), [])
        for name in ("..", escape.replace(os.sep, "/"), "a/../.."):
            with self.subTest(name=name):
                self.assertEqual(unpack.torrent_files(self.folder, magnet=f"magnet:?xt=urn:btih:{'a' * 40}&dn={name}"), [])


class MadokamiFolderTests(FolderTestCase):
    def test_folders_are_named_after_the_library(self):
        self.assertEqual(madokami.save_folder(NAKI + "/v01.zip", "D"), os.path.join("D", "Naki no Ryuu"))
        self.assertEqual(madokami.save_folder("/Manga/O/ON/ONE_/One Piece/%21One Piece [Viz]/v01.cbz", "D"),
                         os.path.join("D", "One Piece", "One Piece [Viz]"))
        self.assertEqual(madokami.save_folder("/Raws/N/NA/NAKI/Naki no Ryuu/v01.zip", "D"),
                         os.path.join("D", "Naki no Ryuu [Raws]"))

    def test_two_or_more_files_share_a_folder_and_a_lone_one_stays_loose(self):
        files = [NAKI + "/c01.zip", NAKI + "/c02.zip"]
        series = self.path("Naki no Ryuu")
        self.assertEqual(madokami.download_folders(files, self.folder), {f: series for f in files})
        self.assertEqual(madokami.download_folders(files[:1], self.folder), {files[0]: self.folder})
        os.mkdir(series)  # an earlier download made it: later chapters join it
        self.assertEqual(madokami.download_folders(files[:1], self.folder), {files[0]: series})

    def pick(self, picked, unpacking=False):
        isolate_store(self)
        save_setting(unpack.SETTING, unpacking)
        saved_to = []

        def download(path, folder, cancel_event=None, progress_cb=None):
            saved_to.append(folder)
            os.makedirs(folder, exist_ok=True)
            return self.make_zip(path.rsplit("/", 1)[-1], ["001.jpg"], folder)

        with patch("torrent_finder.credentials.madokami_config", return_value=("user", "pass")), \
             patch.object(acquisition.MadokamiAcquisition, "_choose_files", return_value=picked), \
             patch("torrent_finder.ui.prompts.download_dir_ready", return_value=True), \
             patch("torrent_finder.constants.get_download_dir", return_value=self.folder), \
             patch("torrent_finder.utils.start_esc_listener", return_value=threading.Event()), \
             patch.object(madokami, "download_file", side_effect=download), \
             patch.object(acquisition.readchar, "readkey", return_value="x"):
            outcome = acquisition.MadokamiAcquisition().pick({"name": "Naki no Ryuu", "mdk_path": NAKI})
        self.assertEqual(outcome.action, "next")
        return saved_to

    def test_a_picked_set_of_chapters_lands_in_one_folder(self):
        saved_to = self.pick([NAKI + "/c01.zip", NAKI + "/c02.zip"])
        self.assertEqual(saved_to, [self.path("Naki no Ryuu")] * 2)
        self.assertEqual(self.tree("Naki no Ryuu"), ["c01.zip", "c02.zip"])

    def test_with_unpacking_on_each_chapter_becomes_a_folder_of_pages(self):
        self.pick([NAKI + "/c01.zip", NAKI + "/c02.zip"], unpacking=True)
        self.assertEqual(self.tree("Naki no Ryuu"), ["c01/001.jpg", "c02/001.jpg"])

    def test_a_batch_groups_madokami_files_like_a_pick(self):
        rows = [SearchResult(name=f"c0{n}", info_hash=f"madokami:{NAKI}/c0{n}.zip", source="Madokami",
                             handle={"mdk_path": f"{NAKI}/c0{n}.zip"}) for n in (1, 2)]
        book = SearchResult(name="Book", info_hash="libgen:1", source="Libgen")
        selection = rows + [book]
        self.assertEqual(acquisition.batch_download_dir(rows[0], selection, self.folder), self.path("Naki no Ryuu"))
        self.assertEqual(acquisition.batch_download_dir(rows[0], [rows[0], book], self.folder), self.folder)
        self.assertEqual(acquisition.batch_download_dir(book, selection, self.folder), self.folder)

    def test_a_batch_item_is_unpacked_and_a_kept_archive_is_noted(self):
        isolate_store(self)
        save_setting(unpack.SETTING, True)
        row = SearchResult(name="c01", info_hash=f"madokami:{NAKI}/c01.rar", source="Madokami",
                           handle={"mdk_path": f"{NAKI}/c01.rar"})

        def download(path, folder, cancel_event=None, progress_cb=None):
            with open(os.path.join(folder, "c01.rar"), "wb") as handle:
                handle.write(b"Rar!")
            return os.path.join(folder, "c01.rar")

        with patch.object(madokami, "download_file", side_effect=download), \
             patch.object(unpack, "_tools", return_value=[]):
            outcome = acquisition.MadokamiAcquisition().batch_item(
                row, download_dir=self.folder, cancel_event=threading.Event(), set_status=lambda _text: None)
        self.assertTrue(outcome.ok)
        self.assertIn("Kept c01.rar packed", outcome.note)


class TorrentDownloadTests(FolderTestCase):
    def test_a_finished_torrent_s_page_archives_unpack_when_the_setting_is_on(self):
        from torrent_finder.torrent_session import TorrentSession

        isolate_store(self)
        os.mkdir(self.path("Naki no Ryuu"))
        self.make_zip("v01.cbz", ["001.jpg"], self.path("Naki no Ryuu"))
        session = TorrentSession({"name": "Naki no Ryuu"}, "magnet:?xt=urn:btih:" + "b" * 40)
        session._files_meta = TorrentMetadata("Naki no Ryuu", [TorrentFile(1, "v01.cbz", 1)])
        with patch("torrent_finder.constants.get_download_dir", return_value=self.folder):
            self.assertEqual(main._unpack_torrent(session), "")
            self.assertEqual(self.tree("Naki no Ryuu"), ["v01.cbz"])  # off by default
            save_setting(unpack.SETTING, True)
            self.assertIn("Unpacked 1 archive", main._unpack_torrent(session))
        self.assertEqual(self.tree("Naki no Ryuu"), ["v01/001.jpg"])


class SettingTests(unittest.TestCase):
    def test_the_toggle_flips_the_saved_setting_and_its_label(self):
        from torrent_finder.ui import prompts
        from torrent_finder.ui.selector import SelectItem

        isolate_store(self)
        item = SelectItem(prompts._unpack_label(False), "toggle_unpack")
        prompts._toggle_unpack(item)
        self.assertTrue(load_setting(unpack.SETTING))
        self.assertIn("ON", item.label)
        prompts._toggle_unpack(item)
        self.assertFalse(load_setting(unpack.SETTING))
        self.assertIn("OFF", item.label)


if __name__ == "__main__":
    unittest.main()
