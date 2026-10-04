"""Server-provided file names stay inside the download folder, and no download
path overwrites or truncates an existing file (review findings, 2026-10-04)."""

import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

import isolation  # noqa: F401  (keeps the user's settings out of reach)
from torrent_finder import jimaku, libgen, madokami, online_fix
from torrent_finder.direct_download import safe_filename, save_response


def response(chunks=(b"data",), url="https://example.test/x", fail_after=None):
    resp = Mock(status_code=200, url=url, headers={})

    def iterate(chunk_size=None):
        for n, chunk in enumerate(chunks):
            if fail_after is not None and n >= fail_after:
                raise requests.ConnectionError("dropped")
            yield chunk
    resp.iter_content.side_effect = iterate
    resp.raise_for_status.return_value = None
    resp.__enter__ = Mock(return_value=resp)
    resp.__exit__ = Mock(return_value=False)
    return resp


class FolderCase(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.root = root.name
        self.folder = os.path.join(self.root, "downloads")
        os.makedirs(self.folder)

    def outside(self):
        return sorted(set(os.listdir(self.root)) - {"downloads"})


class SafeFilenameTests(FolderCase):
    def test_names_are_reduced_to_one_ordinary_file_name(self):
        for raw, safe in (("..\\..\\x.cbz", "x.cbz"), ("a/../b.zip", "b.zip"), ("Re:Zero v01.cbz", "Re_Zero v01.cbz"),
                          ("CON", "_CON"), ("con.txt", "_con.txt"), ("name. ", "name"), ("..", "download"),
                          ("", "download"), ("Q?.torrent", "Q_.torrent"), ("tab\tname.srt", "tab_name.srt")):
            with self.subTest(raw=raw):
                self.assertEqual(safe_filename(raw), safe)
        long_name = safe_filename("A" * 300 + ".epub")
        self.assertEqual((len(long_name), long_name[-5:]), (180, ".epub"))

    def test_the_shared_writer_never_leaves_the_folder(self):
        path = save_response(response(), self.folder, "..\\..\\escaped.cbz")
        self.assertEqual(os.path.dirname(path), self.folder)
        self.assertEqual(self.outside(), [])


class SourceDownloadTests(FolderCase):
    def test_madokami_paths_with_encoded_separators_save_inside(self):
        session = Mock()
        session.get.return_value = response()
        with patch.object(madokami, "_get_session", return_value=session):
            path = madokami.download_file("/Manga/X/a%5C..%5C..%5Cescaped.cbz", self.folder)
        self.assertEqual(os.path.dirname(path), self.folder)
        self.assertEqual(self.outside(), [])

    def test_jimaku_keeps_an_existing_subtitle_when_a_redownload_fails(self):
        existing = os.path.join(self.folder, "episode.srt")
        with open(existing, "w", encoding="utf-8") as fh:
            fh.write("complete subtitles")
        with patch.object(jimaku, "get_download_dir", return_value=self.folder), \
             patch.object(jimaku.requests, "get", return_value=response([b"partial", b"rest"], fail_after=1)), \
             patch.object(jimaku, "console"):
            self.assertIsNone(jimaku._download("https://jimaku.test/f", "episode.srt", "key"))
        with open(existing, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "complete subtitles")
        self.assertEqual(os.listdir(self.folder), ["episode.srt"])  # no partial file either

    def test_jimaku_names_stay_inside_and_new_files_are_numbered(self):
        open(os.path.join(self.folder, "episode.srt"), "w").close()
        with patch.object(jimaku, "get_download_dir", return_value=self.folder), \
             patch.object(jimaku.requests, "get", return_value=response()):
            first = jimaku._download("https://jimaku.test/f", "episode.srt", "key")
            second = jimaku._download("https://jimaku.test/f", "../outside/overwrite.srt", "key")
        self.assertEqual(os.path.basename(first), "episode (1).srt")
        self.assertEqual(os.path.dirname(second), self.folder)
        self.assertEqual(self.outside(), [])

    def test_online_fix_torrents_use_the_url_path_and_keep_existing_files(self):
        open(os.path.join(self.folder, "Game.torrent"), "w").close()
        session = Mock()
        session.get.return_value = response([b"d8:announce"])
        with patch.object(online_fix, "resolve_torrent",
                          return_value="https://uploads.online-fix.me/torrents/Game/Game.torrent?md5=abc"), \
             patch.object(online_fix, "_anon_http", return_value=session):
            path = online_fix.fetch_torrent_for("https://online-fix.me/games/x/1-game.html", self.folder)
        self.assertEqual(os.path.basename(path), "Game (1).torrent")
        session.get.return_value = response([b"d8:"], fail_after=0)
        with patch.object(online_fix, "resolve_torrent",
                          return_value="https://uploads.online-fix.me/torrents/x/..%5C..%5Cescaped.torrent"), \
             patch.object(online_fix, "_anon_http", return_value=session):
            self.assertIsNone(online_fix.fetch_torrent_for("https://online-fix.me/games/x/2-x.html", self.folder))
        self.assertEqual(sorted(os.listdir(self.folder)), ["Game (1).torrent", "Game.torrent"])
        self.assertEqual(self.outside(), [])


class LibgenNameTests(unittest.TestCase):
    def test_content_disposition_names(self):
        self.assertEqual(libgen._disposition_name("attachment; filename*=UTF-8''%D0%98%D0%B4%D0%B8%D0%BE%D1%82.epub"),
                         "Идиот.epub")
        raw = "Идиот.epub".encode("utf-8").decode("latin-1")  # how the HTTP library hands it over
        self.assertEqual(libgen._disposition_name(f'attachment; filename="{raw}"'), "Идиот.epub")
        self.assertEqual(libgen._disposition_name('attachment; filename="plain.epub"'), "plain.epub")
        self.assertEqual(libgen._disposition_name(""), "")


if __name__ == "__main__":
    unittest.main()
