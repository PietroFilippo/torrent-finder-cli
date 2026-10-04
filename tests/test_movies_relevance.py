"""Movies rank the requested film first; typed release tags help instead of hiding it."""

import unittest
from unittest.mock import Mock, patch

from torrent_finder.providers import base
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.result_view import movie_title_score, release_tag_hits, split_release_tags
from torrent_finder.search_result import SearchResult
from torrent_finder.search_session import SearchSession


class MovieTitleScoreTests(unittest.TestCase):
    def test_original_outranks_sequels_and_bundles(self):
        self.assertEqual(movie_title_score("The Matrix (1999) 1080p BrRip x264 - 1.85GB - YIFY", "The Matrix"), 3)
        self.assertEqual(movie_title_score("The Matrix Reloaded (2003) 1080p BrRip x264 - YIFY", "The Matrix"), 2)
        self.assertEqual(movie_title_score("The Matrix Trilogy 1999-2003 1080p BluRay", "The Matrix"), 2)

    def test_typed_tags_numbers_and_years(self):
        cases = [
            ("Finding Nemo (2003) 1080p BrRip x264 - YIFY", "Finding Nemo 1080p", 3),
            ("Procurando.Nemo.2003.Dublado.720p.BRrip.x264", "Procurando Nemo pt-br", 3),
            ("Dune Part Two (2024) [1080p] [WEBRip]", "Dune Part 2", 3),
            ("Rocky II 1979 1080p BluRay", "Rocky 2", 3),
            ("Dark.S02.1080p.NF.WEB-DL", "Dark S02", 3),
            ("Dune (2021) [1080p] [WEBRip]", "Dune 2021", 3),
            ("Dune (1984) [1080p] [BluRay]", "Dune 2021", 2),   # same title, another film
            ("1917 (2019) [1080p] [BluRay]", "1917", 3),          # a title that is a year
        ]
        for name, query, expected in cases:
            with self.subTest(query=query, name=name):
                self.assertEqual(movie_title_score(name, query), expected)

    def test_release_tags_are_split_and_counted(self):
        self.assertEqual(split_release_tags("Finding Nemo pt-br 1080p"), ("Finding Nemo", ("pt-br", "1080p")))
        self.assertEqual(split_release_tags("1080p"), ("1080p", ("1080p",)))
        self.assertEqual(release_tag_hits("Procurando Nemo 2003 PT-BR Dublado 1080p", "Finding Nemo pt-br 1080p"), 2)
        self.assertEqual(release_tag_hits("Finding Nemo 2003 720p", "Finding Nemo pt-br"), 0)


class MovieSearchTests(unittest.TestCase):
    def search(self, query, apibay):
        with patch.object(MovieProvider, "_search_apibay", side_effect=lambda q: list(apibay)) as search, \
             patch.object(MovieProvider, "_search_knaben", return_value=[]), \
             patch.object(MovieProvider, "_search_solidtorrents", return_value=[]), \
             patch.object(MovieProvider, "_search_nyaa", return_value=[]), \
             patch.object(MovieProvider, "_search_yts", return_value=[], create=True):
            return SearchSession([MovieProvider()], [query]).run(), search

    def test_original_first_even_with_fewer_seeders(self):
        results, _ = self.search("The Matrix", [
            SearchResult(name="The Matrix Reloaded (2003) 1080p", info_hash="a" * 40, source="Apibay", seeders=900),
            SearchResult(name="The Matrix (1999) 1080p", info_hash="b" * 40, source="Apibay", seeders=500)])
        self.assertEqual([r.name for r in results], ["The Matrix (1999) 1080p", "The Matrix Reloaded (2003) 1080p"])

    def test_tagged_query_also_searches_the_title_and_prefers_tagged_releases(self):
        results, search = self.search("Finding Nemo pt-br", [
            SearchResult(name="Finding Nemo (2003) 1080p", info_hash="a" * 40, source="Apibay", seeders=900),
            SearchResult(name="Finding Nemo 2003 PT-BR 720p", info_hash="b" * 40, source="Apibay", seeders=10)])
        self.assertEqual({call.args[0] for call in search.call_args_list}, {"Finding Nemo pt-br", "Finding Nemo"})
        self.assertEqual(results[0].name, "Finding Nemo 2003 PT-BR 720p")
        self.assertEqual(MovieProvider().expand_queries("Finding Nemo"), ["Finding Nemo"])


class NyaaDiscoveryTests(unittest.TestCase):
    """Anime's extra 'popular' lookup stays Anime-only now that Movies ranks titles too."""

    def test_only_anime_looks_up_popular_matches(self):
        empty_feed = Mock(status_code=200, text="<rss><channel></channel></rss>")
        for provider, expected in ((MovieProvider(), 0), (AnimeProvider(), 1)):
            with self.subTest(provider=type(provider).__name__), \
                 patch.object(base.requests, "get", return_value=empty_feed), \
                 patch("torrent_finder.nyaa.popular", return_value=[]) as popular, \
                 patch("torrent_finder.nyaa.discovery_query", side_effect=lambda q, rows: q):
                provider._search_nyaa_in("Saki", provider.nyaa_category)
                self.assertEqual(popular.call_count, expected)


if __name__ == "__main__":
    unittest.main()
