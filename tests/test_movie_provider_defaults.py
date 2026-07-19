import unittest
import warnings
from unittest.mock import Mock, patch
from urllib.parse import parse_qs

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from torrent_finder.providers.movie_provider import MovieProvider


def _params(call) -> dict:
    """Return a call's query params whether passed as a dict or a string.

    APIBay requests pass ``params`` as a pre-encoded string so both %20 and
    "+" space forms can be tested; other engines still pass a dict.
    """
    params = call.kwargs["params"]
    if isinstance(params, dict):
        return params
    return {key: values[0] for key, values in parse_qs(params).items()}


class MovieProviderDefaultsTests(unittest.TestCase):
    def setUp(self):
        cache_store_patcher = patch(
            "torrent_finder.providers.base.apibay_cache.store"
        )
        self.cache_store = cache_store_patcher.start()
        self.addCleanup(cache_store_patcher.stop)
        cache_load_patcher = patch(
            "torrent_finder.providers.base.apibay_cache.load", return_value=[]
        )
        self.cache_load = cache_load_patcher.start()
        self.addCleanup(cache_load_patcher.stop)

    def _without_category_fallback(self) -> MovieProvider:
        provider = MovieProvider()
        provider.apibay_fallback_categories = ()
        return provider

    def test_only_apibay_and_nyaa_are_enabled_by_default(self):
        provider = MovieProvider()

        enabled = {engine.name for engine in provider.engines if engine.enabled}
        self.assertEqual(enabled, {"Apibay", "Nyaa"})
        emergency = {
            engine.name for engine in provider.engines
            if engine.emergency_fallback
        }
        self.assertEqual(emergency, {"Knaben"})

    def test_apibay_covers_movie_and_tv_release_categories(self):
        self.assertEqual(
            set(MovieProvider.categories),
            {201, 202, 205, 207, 208, 209},
        )

    def test_apibay_search_keeps_movie_and_tv_categories(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [
            {
                "id": "1",
                "name": "A TV release",
                "info_hash": "a" * 40,
                "seeders": "10",
                "leechers": "1",
                "size": "100",
                "category": "208",
            },
            {
                "id": "2",
                "name": "An unrelated release",
                "info_hash": "b" * 40,
                "seeders": "5",
                "leechers": "1",
                "size": "100",
                "category": "401",
            },
        ]

        with patch(
            "torrent_finder.providers.base.requests.get", return_value=response
        ):
            results = MovieProvider()._search_apibay("show")

        self.assertEqual([result.name for result in results], ["A TV release"])

    def test_apibay_omits_category_for_primary_search(self):
        """APIBay does not treat an omitted category like ``cat=0``.

        This mirrors the live failure where ``finding nemo&cat=0`` returned
        the empty sentinel while the documented ``finding nemo`` request
        returned 100 rows.
        """
        no_results = Mock()
        no_results.raise_for_status.return_value = None
        no_results.json.return_value = [{"id": "0", "name": "No results returned"}]
        hit = Mock()
        hit.raise_for_status.return_value = None
        hit.json.return_value = [
            {
                "id": "12",
                "name": "Finding Nemo (2003)",
                "info_hash": "5" * 40,
                "seeders": "92",
                "leechers": "4",
                "size": "900",
                "category": "207",
            }
        ]

        def respond(*_args, **kwargs):
            return no_results if "cat" in _params(Mock(kwargs=kwargs)) else hit

        with patch(
            "torrent_finder.providers.base.requests.get", side_effect=respond
        ) as get:
            results = self._without_category_fallback()._search_apibay(
                "finding nemo"
            )

        self.assertEqual([result.name for result in results], ["Finding Nemo (2003)"])
        self.assertNotIn("cat", _params(get.call_args_list[0]))

    def test_apibay_retries_uppercase_as_full_lowercase_phrase(self):
        no_results = Mock()
        no_results.raise_for_status.return_value = None
        no_results.json.return_value = [{"id": "0", "name": "No results returned"}]
        hit = Mock()
        hit.raise_for_status.return_value = None
        hit.json.return_value = [
            {
                "id": "13",
                "name": "Finding Nemo (2003)",
                "info_hash": "4" * 40,
                "seeders": "80",
                "leechers": "3",
                "size": "800",
                "category": "207",
            }
        ]

        def respond(*_args, **kwargs):
            params = _params(Mock(kwargs=kwargs))
            return hit if params.get("q") == "finding nemo" else no_results

        with patch(
            "torrent_finder.providers.base.requests.get", side_effect=respond
        ) as get:
            results = self._without_category_fallback()._search_apibay(
                "FINDING NEMO"
            )

        self.assertEqual([result.name for result in results], ["Finding Nemo (2003)"])
        self.assertIn(
            "finding nemo", [_params(call)["q"] for call in get.call_args_list]
        )

    def test_apibay_falls_back_to_historical_movie_category_requests(self):
        no_results = Mock()
        no_results.raise_for_status.return_value = None
        no_results.json.return_value = [{"id": "0", "name": "No results returned"}]

        def category_response() -> Mock:
            response = Mock()
            response.raise_for_status.return_value = None
            response.json.return_value = [
                {
                    "id": "201",
                    "name": "Interstellar movie",
                    "info_hash": "2" * 40,
                    "seeders": "25",
                    "leechers": "2",
                    "size": "250",
                    "category": "201",
                },
                {
                    "id": "207",
                    "name": "Interstellar HD",
                    "info_hash": "3" * 40,
                    "seeders": "30",
                    "leechers": "3",
                    "size": "300",
                    "category": "207",
                },
            ]
            return response

        with patch(
            "torrent_finder.providers.base.requests.get",
            side_effect=[no_results, category_response()],
        ) as get:
            results = MovieProvider()._search_apibay("Interstellar")

        self.assertEqual(
            [result.name for result in results],
            ["Interstellar movie", "Interstellar HD"],
        )
        self.assertNotIn("cat", _params(get.call_args_list[0]))
        self.assertEqual(_params(get.call_args_list[1])["cat"], "201,207")

    def test_apibay_retries_spelled_sequel_number(self):
        no_results = Mock()
        no_results.raise_for_status.return_value = None
        no_results.json.return_value = [{"id": "0", "name": "No results returned"}]
        fallback = Mock()
        fallback.raise_for_status.return_value = None
        fallback.json.return_value = [
            {
                "id": "3",
                "name": "Dune Part Two (2024)",
                "info_hash": "c" * 40,
                "seeders": "20",
                "leechers": "2",
                "size": "200",
                "category": "207",
            }
        ]

        with patch(
            "torrent_finder.providers.base.requests.get",
            side_effect=[no_results] * 4 + [fallback],
        ) as get:
            results = self._without_category_fallback()._search_apibay(
                "dune part two"
            )

        self.assertEqual(
            [result.name for result in results], ["Dune Part Two (2024)"]
        )
        self.assertEqual(
            [_params(call)["q"] for call in get.call_args_list],
            ["dune part two"] * 2 + ["Dune Part Two"] * 2 + ["dune part 2"],
        )

    def test_apibay_retries_with_distinctive_title_token(self):
        no_results = Mock()
        no_results.raise_for_status.return_value = None
        no_results.json.return_value = [{"id": "0", "name": "No results returned"}]
        fallback = Mock()
        fallback.raise_for_status.return_value = None
        fallback.json.return_value = [
            {
                "id": "4",
                "name": "A Minecraft Movie (2025)",
                "info_hash": "d" * 40,
                "seeders": "30",
                "leechers": "3",
                "size": "300",
                "category": "207",
            }
        ]

        with patch(
            "torrent_finder.providers.base.requests.get",
            side_effect=[no_results] * 4 + [fallback],
        ) as get:
            results = self._without_category_fallback()._search_apibay(
                "a minecraft movie"
            )

        self.assertEqual(
            [result.name for result in results], ["A Minecraft Movie (2025)"]
        )
        self.assertEqual(_params(get.call_args_list[4])["q"], "minecraft")

    def test_apibay_retries_when_initial_rows_are_not_movies(self):
        unrelated = Mock()
        unrelated.raise_for_status.return_value = None
        unrelated.json.return_value = [
            {
                "id": "5",
                "name": "Unrelated audio release",
                "info_hash": "e" * 40,
                "seeders": "9",
                "leechers": "1",
                "size": "100",
                "category": "101",
            }
        ]
        fallback = Mock()
        fallback.raise_for_status.return_value = None
        fallback.json.return_value = [
            {
                "id": "6",
                "name": "The Substance (2024)",
                "info_hash": "f" * 40,
                "seeders": "40",
                "leechers": "4",
                "size": "400",
                "category": "207",
            }
        ]

        no_results = Mock()
        no_results.raise_for_status.return_value = None
        no_results.json.return_value = [{"id": "0", "name": "No results returned"}]

        with patch(
            "torrent_finder.providers.base.requests.get",
            side_effect=[unrelated, no_results, no_results, fallback],
        ) as get:
            results = self._without_category_fallback()._search_apibay(
                "the substance movie"
            )

        self.assertEqual([result.name for result in results], ["The Substance (2024)"])
        self.assertEqual(
            [_params(call)["q"] for call in get.call_args_list],
            ["the substance movie"]
            + ["The Substance Movie"] * 2
            + ["substance"],
        )

    def test_apibay_retries_exact_movie_title_with_yts_release_year(self):
        no_results = Mock()
        no_results.raise_for_status.return_value = None
        no_results.json.return_value = [{"id": "0", "name": "No results returned"}]
        yts_metadata = Mock()
        yts_metadata.raise_for_status.return_value = None
        yts_metadata.json.return_value = {
            "status": "ok",
            "data": {
                "movies": [
                    {"title": "The Science of Interstellar", "year": 2014},
                    {"title": "Interstellar", "year": 2014},
                ]
            },
        }
        fallback = Mock()
        fallback.raise_for_status.return_value = None
        fallback.json.return_value = [
            {
                "id": "7",
                "name": "Interstellar (2014)",
                "info_hash": "1" * 40,
                "seeders": "50",
                "leechers": "5",
                "size": "500",
                "category": "207",
            }
        ]

        with patch(
            "torrent_finder.providers.base.requests.get",
            side_effect=[no_results] * 3 + [yts_metadata, fallback],
        ) as get:
            results = self._without_category_fallback()._search_apibay(
                "Interstellar"
            )

        self.assertEqual([result.name for result in results], ["Interstellar (2014)"])
        self.assertEqual(_params(get.call_args_list[0])["q"], "Interstellar")
        self.assertEqual(
            _params(get.call_args_list[3])["query_term"], "Interstellar"
        )
        self.assertEqual(
            _params(get.call_args_list[4])["q"], "Interstellar 2014"
        )

    def test_apibay_retries_title_cased_query_first(self):
        # Apibay can serve a stale empty answer for an all-lowercase query
        # while the title-cased spelling of the same words matches.
        no_results = Mock()
        no_results.raise_for_status.return_value = None
        no_results.json.return_value = [{"id": "0", "name": "No results returned"}]
        recased = Mock()
        recased.raise_for_status.return_value = None
        recased.json.return_value = [
            {
                "id": "9",
                "name": "Fantastic Mr Fox (2009)",
                "info_hash": "8" * 40,
                "seeders": "70",
                "leechers": "7",
                "size": "700",
                "category": "207",
            }
        ]

        with patch(
            "torrent_finder.providers.base.requests.get",
            side_effect=[no_results, no_results, recased],
        ) as get:
            results = self._without_category_fallback()._search_apibay(
                "fantastic mr fox"
            )

        self.assertEqual(
            [result.name for result in results], ["Fantastic Mr Fox (2009)"]
        )
        self.assertEqual(
            [_params(call)["q"] for call in get.call_args_list],
            ["fantastic mr fox"] * 2 + ["Fantastic Mr Fox"],
        )

    def test_apibay_encodes_spaces_as_percent20_not_plus(self):
        # Apibay's q.php treats "+" literally, so form-encoded multi-word
        # queries always hit the no-results sentinel.
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [
            {
                "id": "8",
                "name": "Fantastic Mr Fox (2009)",
                "info_hash": "9" * 40,
                "seeders": "60",
                "leechers": "6",
                "size": "600",
                "category": "207",
            }
        ]

        with patch(
            "torrent_finder.providers.base.requests.get", return_value=response
        ) as get:
            MovieProvider()._search_apibay("Fantastic Mr Fox")

        raw_params = get.call_args.kwargs["params"]
        self.assertIsInstance(raw_params, str)
        self.assertIn("q=Fantastic%20Mr%20Fox", raw_params)
        self.assertNotIn("+", raw_params)

    def test_apibay_retries_empty_answer_with_plus_encoding(self):
        # Some apibay nodes only decode "+" as a space; a %20 no-results
        # answer is retried with the alternate encoding before giving up.
        no_results = Mock()
        no_results.raise_for_status.return_value = None
        no_results.json.return_value = [{"id": "0", "name": "No results returned"}]
        plus_hit = Mock()
        plus_hit.raise_for_status.return_value = None
        plus_hit.json.return_value = [
            {
                "id": "10",
                "name": "Fantastic Mr Fox (2009)",
                "info_hash": "7" * 40,
                "seeders": "80",
                "leechers": "8",
                "size": "800",
                "category": "207",
            }
        ]

        with patch(
            "torrent_finder.providers.base.requests.get",
            side_effect=[no_results, plus_hit],
        ) as get:
            results = self._without_category_fallback()._search_apibay(
                "Fantastic Mr Fox"
            )

        self.assertEqual(
            [result.name for result in results], ["Fantastic Mr Fox (2009)"]
        )
        first, second = [call.kwargs["params"] for call in get.call_args_list]
        self.assertIn("q=Fantastic%20Mr%20Fox", first)
        self.assertIn("q=Fantastic+Mr+Fox", second)

    def test_apibay_does_not_mutate_query_with_random_padding(self):
        no_results = Mock()
        no_results.raise_for_status.return_value = None
        no_results.json.return_value = [{"id": "0", "name": "No results returned"}]
        provider = self._without_category_fallback()

        with (
            patch.object(
                provider, "_apibay_retry_queries", return_value=iter(())
            ),
            patch(
                "torrent_finder.providers.base.requests.get",
                return_value=no_results,
            ) as get,
        ):
            results = provider._search_apibay("Finding Nemo")

        self.assertEqual(results, [])
        raw = [call.kwargs["params"] for call in get.call_args_list]
        self.assertEqual(raw, ["q=Finding%20Nemo", "q=Finding+Nemo"])

    def test_yts_uses_the_current_api_base(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "status": "ok",
            "data": {
                "movies": [
                    {
                        "title_long": "Oppenheimer (2023)",
                        "url": "https://yts.gg/movies/oppenheimer-2023",
                        "torrents": [
                            {
                                "hash": "e" * 40,
                                "quality": "1080p",
                                "type": "bluray",
                                "seeds": 100,
                                "peers": 10,
                                "size_bytes": 1_000,
                            }
                        ],
                    }
                ]
            },
        }

        with patch(
            "torrent_finder.providers.movie_provider.requests.get",
            return_value=response,
        ) as get:
            results = MovieProvider()._search_yts("oppenheimer")

        self.assertEqual(len(results), 1)
        self.assertEqual(
            get.call_args.args[0],
            "https://movies-api.accel.li/api/v2/list_movies.json",
        )


if __name__ == "__main__":
    unittest.main()
