"""Madokami results say what a pick opens, rank the searched series first, and
folders can be browsed into instead of ending at "No files at this level" (P10).

Paths and markup copy a live October 2026 search for "One Piece" and the
"Yokohama Kaidashi Kikou" series folder, which holds files and three release
folders.
"""

import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote, unquote

import isolation  # noqa: F401  (keeps the user's settings out of reach)
from torrent_finder import madokami
from torrent_finder.acquisition import MadokamiAcquisition
from torrent_finder.providers.madokami_provider import MadokamiProvider
from torrent_finder.search_session import SearchSession

ONE_PIECE = "/Manga/O/ON/ONE_/One%20Piece"
SEARCH_PATHS = [
    "/Manga/O/OH/OHAN/Ohana%20Moyou%20no%20One-Piece",
    ONE_PIECE,
    "/Manga/S/SO/SOFT/Soft%20Shell",
    "/Manga/G/GI/GINT/Gintama%20x%20One%20Piece",
    "/Manga/O/ON/ONE_/One%20Piece%20Party",
    "/Manga/_Doujinshi/One%20Piece",
    ONE_PIECE + "/%21One%20Piece%20%5BViz%5D",
    "/Raws/One%20Piece%20Digital%20Colored%20Chapters",
]


def search_page(paths):
    rows = "".join(f'<tr><td><a href="{p}">{unquote(p)}</a></td></tr>' for p in paths)
    return ('<a href="https://manga.madokami.al/logout">Log out</a><a href="/recent">Recent</a>'
            f"<table><thead><tr><th>Path</th></tr></thead><tbody>{rows}</tbody></table>")


def folder_page(path, entries):
    """A folder listing: Back link, then (name, size) rows; folders end in "/"."""
    rows = "".join(f'<tr data-record="1"><td><a href="{path}/{quote(name.rstrip("/"))}" rel="nofollow">'
                   f'{name}</a></td><td>{size}</td><td>2024-08-06 01:28</td><td></td>'
                   '<td><a class="report-link" href="#">Report</a></td></tr>' for name, size in entries)
    return (f'<div id="back-nav"><a href="{path}/..">Back</a></div>'
            f'<table id="index-table"><tbody>{rows}</tbody></table>')


class Response:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status


class LibraryPathTests(unittest.TestCase):
    def test_names_say_what_a_pick_opens(self):
        for path, name in (
            (ONE_PIECE, "One Piece [series folder]"),
            (ONE_PIECE + "/%21One%20Piece%20%5BViz%5D", "One Piece › One Piece [Viz] [folder]"),
            (ONE_PIECE + "/%21One%20Piece%20%5BViz%5D/%21One%20Piece%20%28Digital%29%20%5B1r0n%5D/%21chapters",
             "One Piece › … › One Piece (Digital) [1r0n] › chapters [folder]"),
            ("/Manga/B/BE/BERS/Berserk/Berserk%20v01.cbz", "Berserk › Berserk v01.cbz [file]"),
            ("/Raws/One%20Piece%20Digital%20Colored%20Chapters",
             "One Piece Digital Colored Chapters [Raws · series folder]"),
            ("/Manga/_Doujinshi/One%20Piece", "One Piece [Doujinshi · series folder]"),
            ("/Manga/Oneshots/One%20Piece%20x%20Toriko", "One Piece x Toriko [Oneshots · series folder]"),
            ("/Manga/_Autouploads/AutoUploaded%20from%20Assorted%20Sources/One%20Piece%20Strong%20World",
             "One Piece Strong World [Autouploads · series folder]"),
        ):
            with self.subTest(path=path):
                self.assertEqual(madokami.display_name(path), name)

    def test_the_searched_series_and_its_folders_rank_first(self):
        session = Mock()
        session.get.return_value = Response(search_page(SEARCH_PATHS))
        with patch.object(madokami, "_get_session", return_value=session):
            rows = SearchSession([MadokamiProvider()], ["One Piece"]).run()
        self.assertEqual([r.name for r in rows], [
            "One Piece [series folder]",
            "One Piece › One Piece [Viz] [folder]",
            "One Piece Party [series folder]",
            "One Piece [Doujinshi · series folder]",
            "One Piece Digital Colored Chapters [Raws · series folder]",
            "Ohana Moyou no One-Piece [series folder]",
            "Gintama x One Piece [series folder]",
            "Soft Shell [series folder]",  # found through other names; still listed
        ])
        self.assertEqual(rows[0]["mdk_path"], ONE_PIECE)


YKK = "/Manga/Y/YO/YOKO/Yokohama%20Kaidashi%20Kikou"
YKK_PAGE = folder_page(YKK, [
    ("!Deluxe Edition (Digital) (1r0n)/", "-"),
    ("!old scanlation/", "-"),
    ("Yokohama Kaidashi Kikou - c000-007 (v01) [ykk] [yugen].zip", "48.2M"),
    ("Yokohama Kaidashi Kikou - c008-015 (v02) [ykk] [yugen].zip", "1.5G"),
])


class FolderListingTests(unittest.TestCase):
    def test_listing_keeps_sizes_and_skips_the_back_link(self):
        session = Mock()
        session.get.return_value = Response(YKK_PAGE)
        with patch.object(madokami, "_get_session", return_value=session):
            children = madokami.list_directory(YKK)
        self.assertEqual([(c["name"], c["is_dir"], c["size"]) for c in children], [
            ("Yokohama Kaidashi Kikou - c000-007 (v01) [ykk] [yugen].zip", False, int(48.2 * 1024 ** 2)),
            ("Yokohama Kaidashi Kikou - c008-015 (v02) [ykk] [yugen].zip", False, int(1.5 * 1024 ** 3)),
            ("Deluxe Edition (Digital) (1r0n)", True, 0),
            ("old scanlation", True, 0),
        ])


def child(name, path, is_dir=False, size=0):
    return {"name": name, "path": path, "is_dir": is_dir, "size": size}


SERIES = "/Manga/X/XX/XXXX/Series"
DELUXE = SERIES + "/%21Deluxe"
OLD = SERIES + "/%21old"
LIBRARY = {
    SERIES: [child("Deluxe", DELUXE, True), child("old", OLD, True)],
    DELUXE: [child("Series v01.cbz", DELUXE + "/v01.cbz", size=10), child("Series v02.cbz", DELUXE + "/v02.cbz")],
    OLD: [],
}


class FolderBrowsingTests(unittest.TestCase):
    """Scripted keys: each menu answer names the row to choose, or None for Esc."""

    def browse(self, start, menu_answers, picker_answers, library=LIBRARY):
        menus, pickers = list(menu_answers), list(picker_answers)
        self.menu_titles, self.picker_files, self.starts = [], [], []

        def arrow_select(items, title="", start_index=0, **_):
            self.menu_titles.append(title)
            self.starts.append(start_index)
            label = menus.pop(0)
            return None if label is None else next(i for i, item in enumerate(items) if label in item.label)

        def episode_select_prompt(files):
            self.picker_files.append([(f.name, f.size_bytes) for f in files])
            return pickers.pop(0)

        listing = Mock(side_effect=lambda path: library.get(path))
        with patch.object(madokami, "list_directory", listing), \
             patch("torrent_finder.ui.selector.arrow_select", arrow_select), \
             patch("torrent_finder.ui.prompts.episode_select_prompt", episode_select_prompt), \
             patch("torrent_finder.acquisition.readchar.readkey"), \
             patch("torrent_finder.acquisition.console"):
            chosen = MadokamiAcquisition()._choose_files(start)
        self.listed = [call.args[0] for call in listing.call_args_list]
        self.assertEqual(menus, [], "unused menu answers")
        return chosen

    def test_a_series_of_release_folders_opens_in_place(self):
        chosen = self.browse(SERIES, ["Deluxe"], [[1, 2]])
        self.assertEqual(chosen, [DELUXE + "/v01.cbz", DELUXE + "/v02.cbz"])
        self.assertEqual(self.menu_titles, ["📕 Series"])
        self.assertEqual(self.picker_files, [[("Series v01.cbz", 10), ("Series v02.cbz", 0)]])

    def test_esc_goes_up_one_level_to_the_same_row_then_back_to_results(self):
        # Deluxe picker cancelled → series menu (cursor on Deluxe) → old (empty) → menu → Esc.
        chosen = self.browse(SERIES, ["Deluxe", "old", None], [None])
        self.assertEqual(chosen, [])
        self.assertEqual(self.starts, [0, 0, 1])  # back from "old" lands on "old"
        self.assertEqual(self.listed, [SERIES, DELUXE, OLD])  # each folder listed once

    def test_esc_in_a_nested_folder_menu_returns_to_its_parent_menu(self):
        library = dict(LIBRARY, **{DELUXE: [child("Series v01.cbz", DELUXE + "/v01.cbz"),
                                            child("chapters", DELUXE + "/%21chapters", True)]})
        self.assertEqual(self.browse(SERIES, ["Deluxe", None, None], [], library=library), [])
        self.assertEqual(self.menu_titles, ["📕 Series", "📕 Series › Deluxe", "📕 Series"])

    def test_a_folder_of_files_goes_straight_to_the_picker(self):
        self.assertEqual(self.browse(DELUXE, [], [[2]]), [DELUXE + "/v02.cbz"])
        self.assertEqual(self.menu_titles, [])

    def test_files_beside_folders_are_offered_first(self):
        library = dict(LIBRARY, **{SERIES: [child("Series v00.cbz", SERIES + "/v00.cbz"), *LIBRARY[SERIES]]})
        chosen = self.browse(SERIES, ["file(s) here"], [[1]], library=library)
        self.assertEqual(chosen, [SERIES + "/v00.cbz"])

    def test_a_folder_that_cannot_be_listed_returns_to_its_parent(self):
        library = dict(LIBRARY, **{DELUXE: None})
        self.assertEqual(self.browse(SERIES, ["Deluxe", None], [], library=library), [])
        self.assertEqual(self.listed, [SERIES, DELUXE])


if __name__ == "__main__":
    unittest.main()
