import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs

import requests as requests_mod

from torrent_finder import apibay_cache
from torrent_finder.providers.game_provider import GameProvider


def _params(call) -> dict[str, str]:
    params = parse_qs(call.kwargs["params"])
    return {key: values[0] for key, values in params.items()}


def _response(payload: object) -> Mock:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


class APIBayResilienceTests(unittest.TestCase):
    def test_empty_live_answer_falls_back_to_last_successful_rows(self):
        hit = _response(
            [
                {
                    "id": "18",
                    "name": "Elden Ring",
                    "info_hash": "8" * 40,
                    "seeders": "8",
                    "leechers": "1",
                    "size": "80",
                    "category": "401",
                }
            ]
        )
        no_results = _response([{"id": "0", "name": "No results returned"}])
        provider = GameProvider()
        provider.apibay_fallback_categories = ()

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            apibay_cache,
            "CACHE_PATH",
            str(Path(temp_dir) / "apibay_cache.json"),
        ):
            apibay_cache._reset_for_tests()
            with patch(
                "torrent_finder.providers.base.requests.get", return_value=hit
            ):
                live = provider._search_apibay("elden ring")
            with (
                patch.object(
                    provider, "_apibay_retry_queries", return_value=iter(())
                ),
                patch(
                    "torrent_finder.providers.base.requests.get",
                    return_value=no_results,
                ),
            ):
                cached = provider._search_apibay("elden ring")
            apibay_cache._reset_for_tests()

        self.assertEqual([result.name for result in live], ["Elden Ring"])
        self.assertEqual([result.name for result in cached], ["Elden Ring"])
        self.assertIn("apibay_cached_at", cached[0].extra)

    def test_malformed_rows_do_not_abort_the_encoding_retry(self):
        malformed = _response([None])
        hit = _response(
            [
                {
                    "id": "19",
                    "name": "Elden Ring",
                    "info_hash": "9" * 40,
                    "seeders": "9",
                    "leechers": "1",
                    "size": "90",
                    "category": "401",
                }
            ]
        )
        provider = GameProvider()
        provider.apibay_fallback_categories = ()
        provider.apibay_cache_enabled = False

        with patch(
            "torrent_finder.providers.base.requests.get",
            side_effect=[malformed, hit],
        ) as get:
            results = provider._search_apibay("elden ring")

        self.assertEqual([result.name for result in results], ["Elden Ring"])
        self.assertEqual(get.call_count, 2)

    def test_one_word_transport_failure_gets_one_retry(self):
        hit = _response(
            [
                {
                    "id": "20",
                    "name": "Elden Ring",
                    "info_hash": "a" * 40,
                    "seeders": "10",
                    "leechers": "1",
                    "size": "100",
                    "category": "401",
                }
            ]
        )

        provider = GameProvider()
        provider.apibay_cache_enabled = False
        with patch(
            "torrent_finder.providers.base.requests.get",
            side_effect=[requests_mod.ConnectionError("edge down"), hit],
        ) as get:
            results = provider._search_apibay("elden")

        self.assertEqual([result.name for result in results], ["Elden Ring"])
        self.assertEqual(get.call_count, 2)
        self.assertNotIn("cat", _params(get.call_args_list[0]))

    def test_games_use_one_comma_scoped_fallback(self):
        no_results = _response([{"id": "0", "name": "No results returned"}])
        hit = _response(
            [
                {
                    "id": "21",
                    "name": "Elden Ring",
                    "info_hash": "b" * 40,
                    "seeders": "20",
                    "leechers": "2",
                    "size": "200",
                    "category": "401",
                }
            ]
        )
        expected_category = "400,401,403,404,405,406"
        provider = GameProvider()
        provider.apibay_cache_enabled = False

        def respond(*_args, **kwargs):
            params = parse_qs(kwargs["params"])
            return hit if params.get("cat") == [expected_category] else no_results

        with patch(
            "torrent_finder.providers.base.requests.get", side_effect=respond
        ) as get:
            results = provider._search_apibay("elden ring")

        self.assertEqual([result.name for result in results], ["Elden Ring"])
        self.assertEqual(get.call_count, 3)
        self.assertNotIn("cat", _params(get.call_args_list[0]))
        self.assertEqual(_params(get.call_args_list[-1])["cat"], expected_category)


if __name__ == "__main__":
    unittest.main()
