"""A search that finds nothing says which sources were left out and how to add them."""

import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import isolation  # noqa: F401

from torrent_finder import madokami
from torrent_finder.providers.combined_provider import CombinedProvider
from torrent_finder.providers.fitgirl_provider import FitGirlProvider
from torrent_finder.providers.madokami_provider import MadokamiProvider
from torrent_finder.providers.manga_provider import MangaProvider
from torrent_finder.providers.mobile_provider import MobileProvider
from torrent_finder.search_result import SearchResult
from torrent_finder.search_session import SearchSession

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
