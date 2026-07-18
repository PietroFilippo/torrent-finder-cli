import unittest
import warnings
from unittest.mock import Mock, patch
from urllib.parse import parse_qs

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from torrent_finder.providers.movie_provider import MovieProvider


def _params(call) -> dict:
    """Return a call's query params whether passed as a dict or a string.

    Apibay requests pass ``params`` as a pre-encoded string (q.php does not
    decode "+" as a space); other engines still pass a dict.
    """
    params = call.kwargs["params"]
    if isinstance(params, dict):
        return params
    return {key: values[0] for key, values in parse_qs(params).items()}


class MovieProviderDefaultsTests(unittest.TestCase):
    def _without_category_fallback(self) -> MovieProvider:
        provider = MovieProvider()
        provider.apibay_fallback_categories = ()
        return provider

    def test_only_apibay_and_nyaa_are_enabled_by_default(self):
        provider = MovieProvider()

        enabled = {engine.name for engine in provider.engines if engine.enabled}
        self.assertEqual(enabled, {"Apibay", "Nyaa"})

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

    def test_apibay_falls_back_to_historical_movie_category_requests(self):
        no_results = Mock()
        no_results.raise_for_status.return_value = None
        no_results.json.return_value = [{"id": "0", "name": "No results returned"}]

        def category_response(category: str, name: str, info_hash: str) -> Mock:
            response = Mock()
            response.raise_for_status.return_value = None
            response.json.return_value = [
                {
                    "id": category,
                    "name": name,
                    "info_hash": info_hash,
                    "seeders": "25",
                    "leechers": "2",
                    "size": "250",
                    "category": category,
                }
            ]
            return response

        with patch(
            "torrent_finder.providers.base.requests.get",
            side_effect=[
                no_results,
                category_response("201", "Interstellar movie", "2" * 40),
                category_response("207", "Interstellar HD", "3" * 40),
            ],
        ) as get:
            results = MovieProvider()._search_apibay("Interstellar")

        self.assertEqual(
            [result.name for result in results],
            ["Interstellar movie", "Interstellar HD"],
        )
        self.assertEqual(
            [_params(call)["cat"] for call in get.call_args_list],
            ["0", "201", "207"],
        )

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
            side_effect=[no_results, no_results, fallback],
        ) as get:
            results = self._without_category_fallback()._search_apibay(
                "dune part two"
            )

        self.assertEqual(
            [result.name for result in results], ["Dune Part Two (2024)"]
        )
        self.assertEqual(
            [_params(call)["q"] for call in get.call_args_list],
            ["dune part two", "Dune Part Two", "dune part 2"],
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
            side_effect=[no_results, no_results, fallback],
        ) as get:
            results = self._without_category_fallback()._search_apibay(
                "a minecraft movie"
            )

        self.assertEqual(
            [result.name for result in results], ["A Minecraft Movie (2025)"]
        )
        self.assertEqual(_params(get.call_args_list[2])["q"], "minecraft")

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
            side_effect=[unrelated, no_results, fallback],
        ) as get:
            results = self._without_category_fallback()._search_apibay(
                "the substance movie"
            )

        self.assertEqual([result.name for result in results], ["The Substance (2024)"])
        self.assertEqual(
            [_params(call)["q"] for call in get.call_args_list],
            ["the substance movie", "The Substance Movie", "substance"],
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
            side_effect=[no_results, yts_metadata, fallback],
        ) as get:
            results = self._without_category_fallback()._search_apibay(
                "Interstellar"
            )

        self.assertEqual([result.name for result in results], ["Interstellar (2014)"])
        self.assertEqual(_params(get.call_args_list[0])["q"], "Interstellar")
        self.assertEqual(
            _params(get.call_args_list[1])["query_term"], "Interstellar"
        )
        self.assertEqual(
            _params(get.call_args_list[2])["q"], "Interstellar 2014"
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
            side_effect=[no_results, recased],
        ) as get:
            results = self._without_category_fallback()._search_apibay(
                "fantastic mr fox"
            )

        self.assertEqual(
            [result.name for result in results], ["Fantastic Mr Fox (2009)"]
        )
        self.assertEqual(
            [_params(call)["q"] for call in get.call_args_list],
            ["fantastic mr fox", "Fantastic Mr Fox"],
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
