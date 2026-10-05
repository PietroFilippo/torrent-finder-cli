import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import requests

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from torrent_finder import knaben
from torrent_finder.ui.table import _selected_metadata, _table_layout


def _response(payload):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


class KnabenSearchTests(unittest.TestCase):
    def test_search_is_category_scoped_safe_bounded_and_normalized(self):
        duplicate_hash = "A" * 40
        payload = {
            "hits": [
                {
                    "title": "Fantastic Mr. Fox",
                    "hash": duplicate_hash,
                    "seeders": "42",
                    "peers": "3",
                    "bytes": "1024",
                    "details": "https://example.test/details",
                    "tracker": "Example Tracker",
                    "category": "Movies / HD",
                    "lastSeen": "2026-07-18T10:00:00",
                    "virusDetection": 0.02,
                },
                {
                    "title": "Duplicate",
                    "hash": duplicate_hash.lower(),
                    "seeders": 1,
                },
                {
                    "title": "Missing hash",
                    "hash": None,
                },
                {
                    "title": "Malformed hash",
                    "hash": "not-an-info-hash",
                },
            ]
        }

        with patch(
            "torrent_finder.knaben.requests.get",
            return_value=_response(payload),
        ) as get:
            results = knaben.search("fantastic mr. fox", (3_000_000, 3_008_000))

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.name, "Fantastic Mr. Fox")
        self.assertEqual(result.info_hash, duplicate_hash.lower())
        self.assertEqual(result.seeders, 42)
        self.assertEqual(result.leechers, 3)
        self.assertEqual(result.size, 1024)
        self.assertEqual(result.source, "Knaben")
        self.assertEqual(result.extra["knaben_tracker"], "Example Tracker")
        self.assertEqual(result.extra["knaben_category"], "Movies / HD")
        self.assertEqual(result.extra["knaben_last_seen"], "2026-07-18T10:00:00")
        metadata = _selected_metadata(
            results, 0, _table_layout(120, False), False
        )
        self.assertIn("Knaben tracker: Example Tracker", metadata.plain)

        request = get.call_args
        url = urlsplit(request.args[0])
        self.assertEqual(f"{url.scheme}://{url.netloc}{url.path}", knaben.API_URL)
        self.assertEqual(request.kwargs["timeout"], 15)
        # v1's request in v2 terms: titles, by seeders, 50 a page, zero-seed rows
        # kept ("dead"); unsafe and adult rows stay hidden (no "unsafe"/"xxx").
        self.assertEqual(
            parse_qs(url.query, keep_blank_values=True),
            {
                "q": ["fantastic mr. fox"],
                "sf": ["title"],
                "o": ["seeders"],
                "d": ["desc"],
                "c": ["3000000,3008000"],
                "s": ["50"],
                "f": ["0"],
                "dead": [""],
            },
        )

    def test_search_fails_closed_on_network_or_payload_errors(self):
        with patch(
            "torrent_finder.knaben.requests.get",
            side_effect=requests.ConnectionError("offline"),
        ):
            self.assertEqual(knaben.search("query", (3_000_000,)), [])

        with patch(
            "torrent_finder.knaben.requests.get",
            return_value=_response({"hits": "not-a-list"}),
        ):
            self.assertEqual(knaben.search("query", (3_000_000,)), [])

    def test_empty_query_does_not_make_a_request(self):
        with patch("torrent_finder.knaben.requests.get") as get:
            self.assertEqual(knaben.search("   ", (3_000_000,)), [])
        get.assert_not_called()

    def test_missing_category_scope_does_not_make_a_request(self):
        with patch("torrent_finder.knaben.requests.get") as get:
            self.assertEqual(knaben.search("query", ()), [])
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
