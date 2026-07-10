import unittest

from torrent_finder.creator_search import fan_out
from torrent_finder.filters import FilterConfig, FilterPreset
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.resolvers.types import Work
from torrent_finder.search_result import SearchResult


class FakeProvider(BaseProvider):
    name = "Fake"
    slug = "fake"
    icon = "?"
    categories = []

    def __init__(self, engines):
        self._test_engines = engines
        super().__init__()

    def _init_engines(self):
        return [
            SearchEngine(name, "?", fn, enabled=enabled)
            for name, fn, enabled in self._test_engines
        ]


class SearchResultContractTests(unittest.TestCase):
    def test_from_mapping_coerces_numbers_and_preserves_legacy_handle_keys(self):
        result = SearchResult.from_mapping({
            "name": "Ru row",
            "info_hash": "123",
            "seeders": "9",
            "leechers": "4",
            "size": "2048",
            "source": "RuTracker",
            "page_url": "https://example.test/topic",
            "rt_topic_id": "987",
            "unexpected": "kept",
        })

        self.assertEqual(result.seeders, 9)
        self.assertEqual(result.leechers, 4)
        self.assertEqual(result.size, 2048)
        self.assertEqual(result.handle, {"rt_topic_id": "987"})
        self.assertEqual(result.get("rt_topic_id"), "987")
        self.assertEqual(result.get("unexpected"), "kept")

class BaseProviderSearchContractTests(unittest.TestCase):
    def test_search_merges_enabled_engines_dedupes_hashes_and_sorts_by_seeders(self):
        def engine_one(query):
            self.assertEqual(query, "query")
            return [
                {
                    "name": "Low seed duplicate",
                    "info_hash": "ABC",
                    "seeders": "2",
                    "leechers": "0",
                    "size": "100",
                    "source": "One",
                },
                {
                    "name": "Middle",
                    "info_hash": "MID",
                    "seeders": "9",
                    "leechers": "1",
                    "size": "200",
                    "source": "One",
                },
            ]

        def engine_two(query):
            self.assertEqual(query, "query")
            return [
                {
                    "name": "Disabled duplicate casing",
                    "info_hash": "abc",
                    "seeders": "2",
                    "leechers": "0",
                    "size": "100",
                    "source": "Two",
                },
                {
                    "name": "Top",
                    "info_hash": "TOP",
                    "seeders": "20",
                    "leechers": "2",
                    "size": "300",
                    "source": "Two",
                },
            ]

        provider = FakeProvider(
            [
                ("one", engine_one, True),
                ("two", engine_two, True),
            ]
        )

        results = provider.search("query")

        self.assertTrue(all(isinstance(r, SearchResult) for r in results))
        self.assertEqual([r.info_hash.lower() for r in results], ["top", "mid", "abc"])
        self.assertEqual([r.seeders for r in results], [20, 9, 2])

    def test_search_applies_default_presets_and_cli_filters_to_dict_results(self):
        def engine(query):
            return [
                {
                    "name": "Clean Game",
                    "info_hash": "good",
                    "seeders": "7",
                    "leechers": "0",
                    "size": "100",
                    "source": "FitGirl",
                },
                {
                    "name": "Clean Low Seeds",
                    "info_hash": "low",
                    "seeders": "3",
                    "leechers": "0",
                    "size": "100",
                    "source": "FitGirl",
                },
                {
                    "name": "Cam Release",
                    "info_hash": "cam",
                    "seeders": "8",
                    "leechers": "0",
                    "size": "100",
                    "source": "FitGirl",
                },
                {
                    "name": "Other Source",
                    "info_hash": "other",
                    "seeders": "8",
                    "leechers": "0",
                    "size": "100",
                    "source": "Other",
                },
            ]

        provider = FakeProvider([("one", engine, True)])
        provider.default_filters = FilterConfig(min_seeds=5)
        provider.active_presets = [
            FilterPreset("Repacks Only", FilterConfig(include_keywords=["fitgirl"]))
        ]

        results = provider.search(
            "query",
            cli_filters=FilterConfig(exclude_keywords=["cam"]),
        )

        self.assertTrue(all(isinstance(r, SearchResult) for r in results))
        self.assertEqual([r.info_hash for r in results], ["good"])


class CreatorFanOutContractTests(unittest.TestCase):
    def test_fan_out_searches_titles_and_alt_titles_dedupes_and_tags_origin(self):
        class RecordingProvider:
            def __init__(self):
                self.calls = []

            def search(self, query, cli_filters=None):
                self.calls.append((query, cli_filters))
                rows = {
                    "Primary": [
                        {
                            "name": "Primary row",
                            "info_hash": "h1",
                            "seeders": "1",
                            "source": "Fake",
                        }
                    ],
                    "Alt": [
                        {
                            "name": "Duplicate row",
                            "info_hash": "h1",
                            "seeders": "1",
                            "source": "Fake",
                        },
                        {
                            "name": "Alt row",
                            "info_hash": "h2",
                            "seeders": "5",
                            "source": "Fake",
                        },
                    ],
                    "Other": [
                        {
                            "name": "Other row",
                            "info_hash": "h3",
                            "seeders": "20",
                            "source": "Fake",
                        }
                    ],
                }
                return rows[query]

        provider = RecordingProvider()
        cli_filters = FilterConfig(include_keywords=["x"])
        works = [
            Work(title="Primary", alt_titles=("Alt", "Primary", "")),
            Work(title="Other"),
        ]

        results = fan_out(provider, works, cli_filters=cli_filters, max_workers=2)

        self.assertEqual({q for q, _ in provider.calls}, {"Primary", "Alt", "Other"})
        self.assertTrue(all(filters is cli_filters for _, filters in provider.calls))
        self.assertTrue(all(isinstance(r, SearchResult) for r in results))
        self.assertEqual([r.info_hash for r in results], ["h3", "h2", "h1"])
        self.assertEqual([r.from_work for r in results], ["Other", "Primary", "Primary"])


if __name__ == "__main__":
    unittest.main()
