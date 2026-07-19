import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from torrent_finder import apibay_cache
from torrent_finder.search_result import SearchResult
from torrent_finder.ui.table import _source_label, _table_caption, _table_layout


class APIBayCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache_path_patch = patch.object(
            apibay_cache,
            "CACHE_PATH",
            str(Path(self.temp_dir.name) / "apibay_cache.json"),
        )
        self.cache_path_patch.start()
        self.addCleanup(self.cache_path_patch.stop)
        apibay_cache._reset_for_tests()
        self.addCleanup(apibay_cache._reset_for_tests)

    def test_successful_rows_round_trip_by_provider_and_normalized_query(self):
        row = SearchResult(
            name="Fantastic Mr. Fox",
            info_hash="a" * 40,
            seeders=68,
            leechers=2,
            size=100,
            source="Apibay",
            page_url="https://thepiratebay.org/description.php?id=1",
        )

        apibay_cache.store(
            "movies", "  Fantastic   MR. Fox ", [row], now=1_234.5
        )

        cached = apibay_cache.load("movies", "fantastic mr. fox")

        self.assertEqual([result.name for result in cached], ["Fantastic Mr. Fox"])
        self.assertEqual(cached[0].source, "Apibay")
        self.assertEqual(cached[0].extra["apibay_cached_at"], 1_234.5)
        self.assertEqual(_source_label(cached[0]), "Apibay*")
        caption = _table_caption(
            cached,
            selected_idx=0,
            layout=_table_layout(120, False),
            show_from=False,
            total_pages=1,
            picked=frozenset(),
        )
        self.assertIn("cached last-known-good", caption.plain)
        self.assertEqual(apibay_cache.load("books", "fantastic mr. fox"), [])

    def test_cache_evicts_the_oldest_successful_query(self):
        with patch.object(apibay_cache, "_MAX_ENTRIES", 2):
            for index, query in enumerate(("one", "two", "three"), start=1):
                apibay_cache.store(
                    "movies",
                    query,
                    [
                        SearchResult(
                            name=query,
                            info_hash=str(index) * 40,
                            source="Apibay",
                        )
                    ],
                    now=float(index),
                )

        self.assertEqual(apibay_cache.load("movies", "one"), [])
        self.assertEqual([r.name for r in apibay_cache.load("movies", "two")], ["two"])
        self.assertEqual(
            [r.name for r in apibay_cache.load("movies", "three")], ["three"]
        )


if __name__ == "__main__":
    unittest.main()
