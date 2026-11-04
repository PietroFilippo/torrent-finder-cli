"""A search that finds nothing says which sources were left out and how to add them."""

import io
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

import readchar
from rich.console import Console

import isolation  # noqa: F401

from torrent_finder import madokami
from torrent_finder.filters import FilterConfig
from torrent_finder.providers.combined_provider import CombinedProvider
from torrent_finder.providers.fitgirl_provider import FitGirlProvider
from torrent_finder.providers.madokami_provider import MadokamiProvider
from torrent_finder.providers.manga_provider import MangaProvider
from torrent_finder.providers.mobile_provider import MobileProvider
from torrent_finder.search_result import SearchResult
from torrent_finder.search_session import SearchResults, SearchSession
from torrent_finder.ui import search_diagnostics, table

PUBLIC = ("_search_nyaa", "_search_nyaa_raw", "_search_nyaa_other", "_search_apibay", "_search_knaben")
LOGIN = {"username": "reader", "password": "secret"}


def library_row(path="/Manga/M/MA/MAHJ/Mahjong Hishouden - Naki no Ryuu"):
    return SearchResult(name=madokami.display_name(path), info_hash=f"madokami:{path}", seeders=0,
                        leechers=0, size=0, source="Madokami", page_url=madokami._BASE + path,
                        handle={"mdk_path": path})


class MangaAdviceTests(unittest.TestCase):
    def search(self, query="naki no ryuu", *, login=None, madokami_rows=(), public_rows=()):
        """A Manga · General search with every engine stubbed; returns (results, madokami mock)."""
        library = Mock(return_value=list(madokami_rows))
        with ExitStack() as stack:
            for name in PUBLIC:
                stack.enter_context(patch.object(MangaProvider, name, return_value=list(public_rows)))
            stack.enter_context(patch.object(MangaProvider, "_search_madokami", library))
            stack.enter_context(patch("torrent_finder.providers.manga_provider.madokami_config",
                                      return_value=login))
            results = SearchSession([MangaProvider()], [query]).run()
        return results, library

    def test_nothing_found_names_the_raw_and_other_language_engines(self):
        results, _ = self.search()
        self.assertEqual([], list(results))
        notices = "\n".join(results.notices)
        self.assertIn("Nyaa (Raw) is off", notices)
        self.assertIn("Type raw after the title", notices)
        self.assertIn("Nyaa (Non-English) is off", notices)

    def test_a_raw_search_does_not_suggest_raw(self):
        results, _ = self.search("naki no ryuu raw")
        self.assertNotIn("Nyaa (Raw) is off", "\n".join(results.notices))

    def test_found_results_carry_no_advice(self):
        row = SearchResult(name="Naki no Ryuu v01", info_hash="a" * 40, seeders=3, leechers=0, size=1)
        results, _ = self.search(public_rows=[row])
        self.assertEqual(["Naki no Ryuu v01"], [r.name for r in results])
        self.assertFalse(any("is off" in notice for notice in results.notices))

    def test_without_a_login_madokami_is_left_out_quietly_and_suggested(self):
        results, library = self.search()
        library.assert_not_called()
        diagnostic = next(d for d in results.session.diagnostics if d.engine == "Madokami")
        self.assertEqual("off", diagnostic.status)  # not a failure: nothing to retry
        self.assertFalse(results.session.can_retry)
        self.assertTrue(any("save a Madokami login in Credentials" in n for n in results.notices))

    def test_with_a_login_general_searches_madokami_too(self):
        results, library = self.search(login=LOGIN, madokami_rows=[library_row()])
        library.assert_called_once_with("naki no ryuu")
        self.assertEqual(["Madokami"], [r.get("source") for r in results])
        self.assertEqual("Mahjong Hishouden - Naki no Ryuu [series folder]", results[0].name)
        self.assertFalse(any("Madokami" in notice for notice in results.notices))

    def test_madokami_turned_off_says_where_to_turn_it_on(self):
        provider = MangaProvider()
        next(e for e in provider.engines if e.name == "Madokami").set_mode("off")
        with ExitStack() as stack:
            for name in (*PUBLIC, "_search_madokami"):
                stack.enter_context(patch.object(provider, name, return_value=[]))
            stack.enter_context(patch("torrent_finder.providers.manga_provider.madokami_config",
                                      return_value=LOGIN))
            results = SearchSession([provider], ["naki no ryuu"]).run()
        self.assertIn("Madokami is off: turn it on in Filters & engines to search its library too.",
                      results.notices)


class MadokamiInGeneralTests(unittest.TestCase):
    def search(self, query, rows, cli_filters=None):
        with ExitStack() as stack:
            for name in PUBLIC:
                stack.enter_context(patch.object(MangaProvider, name, return_value=[]))
            stack.enter_context(patch.object(MangaProvider, "_search_madokami", return_value=rows))
            stack.enter_context(patch("torrent_finder.providers.manga_provider.madokami_config",
                                      return_value=LOGIN))
            return SearchSession([MangaProvider()], [query], cli_filters).run()

    def test_a_seed_minimum_keeps_direct_downloads(self):
        results = self.search("naki no ryuu", [library_row()], FilterConfig(min_seeds=1))
        self.assertEqual(["Madokami"], [r.get("source") for r in results])  # no swarm to count

    def test_a_language_typed_after_the_title_does_not_rank_the_folder_down(self):
        provider = MangaProvider()
        folder = library_row("/Manga/B/BE/BERS/Berserk")
        self.assertEqual(provider.title_relevance(folder, "Berserk portuguese"),
                         provider.title_relevance(folder, "Berserk"))

    def test_a_row_both_find_is_credited_to_madokami(self):
        session = Mock()
        with ExitStack() as stack:
            for name in PUBLIC:
                stack.enter_context(patch.object(MangaProvider, name, return_value=[]))
            stack.enter_context(patch("torrent_finder.providers.manga_provider.madokami_config",
                                      return_value=LOGIN))
            stack.enter_context(patch.object(madokami, "_get_session", return_value=session))
            stack.enter_context(patch.object(madokami, "_search_paths",
                                             return_value=["/Manga/M/MA/MAHJ/Mahjong Hishouden - Naki no Ryuu"]))
            results = SearchSession([MangaProvider(), MadokamiProvider()], ["naki no ryuu"], combined=True).run()
        self.assertEqual(["madokami"], [r.get("provider_slug") for r in results])

    def test_shared_results_belong_to_the_login_that_fetched_them(self):
        first, second = Mock(auth=(b"reader", b"secret")), Mock(auth=(b"reader", b"changed"))
        with patch.object(madokami, "_search_paths", return_value=["/Manga/B/BE/BERS/Berserk"]) as paths:
            with patch.object(madokami, "_get_session", return_value=first):
                madokami.search("Berserk")
                madokami.search("Berserk")  # shared
            # The key is the session's own login, read once: a change of saved
            # credentials between two reads cannot file one login's rows under another.
            with patch.object(madokami, "_get_session", return_value=second), \
                 patch.object(madokami, "madokami_config", return_value=LOGIN):
                madokami.search("Berserk")  # another login asks again
        self.assertEqual(paths.call_count, 2)

    def test_other_overlaps_keep_their_credit(self):
        """Manga · General defers to Madokami only: a torrent Books finds too stays Manga's."""
        from torrent_finder.providers.book_provider import BookProvider
        row = SearchResult(name="Berserk v01 Color.cbz", info_hash="c" * 40, seeders=5, leechers=0, size=1,
                           source="Knaben")
        with ExitStack() as stack:
            for name in PUBLIC:
                stack.enter_context(patch.object(MangaProvider, name, return_value=[row]))
            for name in ("_search_libgen", "_search_apibay", "_search_knaben", "_search_solidtorrents"):
                stack.enter_context(patch.object(BookProvider, name, return_value=[row]))
            results = SearchSession([MangaProvider(), BookProvider()], ["Berserk"], combined=True).run()
        self.assertEqual(["manga"], [r.get("provider_slug") for r in results])


class NoticeScreenTests(unittest.TestCase):
    ADVICE = "Nyaa (Raw) is off, and Japanese raw scans are often only there."

    def test_an_empty_search_shows_its_advice_and_n_lists_it(self):
        session = SimpleNamespace(diagnostics=(), can_retry=False, can_load_more=False, queries=["naki no ryuu"])
        results = SearchResults([], [self.ADVICE], session=session)
        drawn = []

        class Screen:  # what the results screen asks Rich to draw, without a terminal
            def __init__(self, renderable, **_):
                drawn.append(renderable)

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def update(self, renderable, **_):
                drawn.append(renderable)

            def start(self, *_, **__):
                pass

            stop = refresh = start

        screen = Console(file=io.StringIO(), width=100, height=40, color_system=None)
        with patch.object(table, "console", screen), patch.object(table, "Live", Screen), \
             patch.object(search_diagnostics, "diagnostics_menu", return_value=None) as menu, \
             patch.object(table.readchar, "readkey", side_effect=["n", readchar.key.ESC]):
            table.interactive_select(results, self.ADVICE)
            screen.print(drawn[0])
        self.assertIn("Nyaa (Raw) is off", screen.file.getvalue())  # on the results screen
        self.assertEqual(list(menu.call_args.args[1]), [self.ADVICE])  # and in diagnostics

    def drive(self, results, note, keys, width=110, height=40, **patches):
        """Run the results screen headless; return the text of its last frame."""
        drawn = []

        class Screen:
            def __init__(self, renderable, **_):
                drawn.append(renderable)

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def update(self, renderable, **_):
                drawn.append(renderable)

            def start(self, *_, **__):
                pass

            stop = refresh = start

        screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
        with ExitStack() as stack:
            stack.enter_context(patch.object(table, "console", screen))
            stack.enter_context(patch.object(table, "Live", Screen))
            stack.enter_context(patch.object(table.readchar, "readkey", side_effect=keys))
            for target, value in patches.items():
                stack.enter_context(patch.object(search_diagnostics, target, value))
            table.interactive_select(results, note)
            screen.print(drawn[-1])
        return screen.file.getvalue()

    def test_notices_show_without_a_note_from_the_caller(self):
        """Creator, discovery and saved searches pass no note: the notices still show."""
        session = SimpleNamespace(diagnostics=(), can_retry=False, can_load_more=False, queries=["x"])
        shown = self.drive(SearchResults([], [self.ADVICE], session=session), "", [readchar.key.ESC])
        self.assertIn("Nyaa (Raw) is off", shown)

    def test_a_refresh_keeps_the_missing_titles_and_replaces_the_notices(self):
        rows = [SearchResult.from_mapping({"name": "Berserk v01", "info_hash": "a" * 40, "seeders": 3,
                                           "source": "Nyaa", "matched_queries": ["Berserk"]})]
        session = SimpleNamespace(diagnostics=(), can_retry=False, can_load_more=True, alias_of={"Berserc": "Berserk"},
                                  queries=["Berserk", "Monster", "Berserc"])
        results = SearchResults(rows, ["OLD FAILURE"], session=session)
        updated = SearchResults(rows, ["NEW FAILURE"], session=session)
        shown = self.drive(results, "", ["m", readchar.key.ESC], run_action=Mock(return_value=(updated, None)))
        self.assertIn("No torrents for 1 of 2 titles: Monster", shown)  # the other spelling is no title
        self.assertIn("NEW FAILURE", shown)
        self.assertNotIn("OLD FAILURE", shown)

    def test_short_windows_keep_the_key_bar_with_every_kind_of_notice(self):
        """Context, missing titles and notices never push the keys off a short screen."""
        rows = [SearchResult.from_mapping({"name": "Berserk v01", "info_hash": "a" * 40, "seeders": 3,
                                           "source": "Nyaa", "matched_queries": ["Berserk"]})]
        session = SimpleNamespace(diagnostics=(), can_retry=True, can_load_more=True, alias_of={},
                                  queries=["Berserk", "Monster"])
        for width, height in ((40, 10), (80, 8), (40, 12), (60, 16), (80, 24), (110, 40)):
            with self.subTest(width=width, height=height):
                results = SearchResults(rows, ["Nyaa / Knaben: timed out.", self.ADVICE], session=session)
                shown = self.drive(results, "Replayed with older filters.", [readchar.key.ESC],
                                   width=width, height=height)
                lines = shown.rstrip("\n").splitlines()
                self.assertLessEqual(len(lines), height)
                self.assertIn("Esc", shown)

    def test_notices_reach_diagnostics_whole(self):
        """Two notices sharing a line both keep it: notices are de-duplicated whole."""
        session = SimpleNamespace(diagnostics=(), can_retry=False, can_load_more=False, queries=["x"])
        notices = ["Engine A:\nPermission denied; verify login.", "Engine B:\nPermission denied; verify login."]
        results = SearchResults([], [*notices, notices[0]], session=session)
        menu = Mock(return_value=None)
        self.drive(results, "", ["n", readchar.key.ESC], diagnostics_menu=menu)
        self.assertEqual(list(menu.call_args.args[1]), notices)

    def test_the_compact_count_counts_notices_not_lines(self):
        notices = ["Engine A:\nPermission denied; verify login.", "Engine B:\nPermission denied; verify login."]
        shown = self.drive(SearchResults([], notices), "", [readchar.key.ESC], width=40, height=10)
        self.assertIn("2 search notices", shown)  # no session: the one-line count stands in

    def test_the_notice_reader_opens_a_notice_whole(self):
        long = "Madokami: " + "a long explanation that a short window clips " * 6
        with patch("torrent_finder.ui.selector.arrow_select", side_effect=[0, None]), \
             patch.object(search_diagnostics, "read_details") as read:
            table._show_search_notices([long])
        self.assertEqual(read.call_args.args[0], long)

    def test_diagnostics_list_the_notices_first(self):
        captured = {}
        session = SimpleNamespace(diagnostics=(), can_retry=False, can_load_more=False, queries=["x"],
                                  page_states=lambda: ())
        with patch.object(search_diagnostics, "arrow_select",
                          side_effect=lambda items, **kw: captured.update(items=items)):
            search_diagnostics.diagnostics_menu(session, [self.ADVICE])
        labels = [item.label for item in captured["items"]]
        self.assertEqual(labels[0], "Search notices")
        self.assertEqual(captured["items"][1].value, ("notice", self.ADVICE))


class SiblingAdviceTests(unittest.TestCase):
    def test_an_empty_madokami_search_points_to_manga_general(self):
        with patch.object(MadokamiProvider, "_search_madokami", return_value=[]):
            results = SearchSession([MadokamiProvider()], ["naki no ryuu"]).run()
        self.assertTrue(any(n.startswith("Manga · General searches public trackers") for n in results.notices))

    def test_no_sibling_advice_when_the_sibling_was_searched_too(self):
        with ExitStack() as stack:
            for name in PUBLIC:
                stack.enter_context(patch.object(MangaProvider, name, return_value=[]))
            stack.enter_context(patch.object(MadokamiProvider, "_search_madokami", return_value=[]))
            results = SearchSession([MangaProvider(), MadokamiProvider()], ["naki no ryuu"], combined=True).run()
        self.assertFalse(any(n.startswith("Manga · General") for n in results.notices))

    def test_an_empty_fitgirl_search_points_to_games_general(self):
        with patch.object(FitGirlProvider, "_search_fitgirl", return_value=[]):
            results = SearchSession([FitGirlProvider()], ["nothing here"]).run()
        self.assertIn("Games · General searches public trackers, Online-Fix and FitGirl together.", results.notices)

    def test_an_empty_mobile_search_mentions_f_droid(self):
        with ExitStack() as stack:
            for name in ("_search_knaben", "_search_apibay", "_search_solidtorrents", "_search_fdroid"):
                stack.enter_context(patch.object(MobileProvider, name, return_value=[]))
            results = SearchSession([MobileProvider()], ["obscure app"]).run()
        self.assertTrue(any(n.startswith("F-Droid is off") for n in results.notices))

    def test_a_combined_search_keeps_madokami_rows_once(self):
        combined = CombinedProvider([MangaProvider(), MadokamiProvider()])
        combined.restore({})
        session = Mock()
        session.get.return_value = Mock(status_code=200, text="")
        with ExitStack() as stack:
            for name in PUBLIC:
                stack.enter_context(patch.object(MangaProvider, name, return_value=[]))
            stack.enter_context(patch("torrent_finder.providers.manga_provider.madokami_config",
                                      return_value=LOGIN))
            stack.enter_context(patch.object(madokami, "_get_session", return_value=session))
            stack.enter_context(patch.object(madokami, "_search_paths",
                                             return_value=["/Manga/M/MA/MAHJ/Mahjong Hishouden - Naki no Ryuu"]))
            results = combined.search("naki no ryuu")
            self.assertEqual(1, madokami._search_paths.call_count)  # one request set for both providers
        self.assertEqual(["Mahjong Hishouden - Naki no Ryuu [series folder]"], [r.name for r in results])


if __name__ == "__main__":
    unittest.main()
