import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from torrent_finder.providers import get_provider
from torrent_finder.providers.combined_provider import CombinedProvider
from torrent_finder.resolvers import topics
from torrent_finder.resolvers.titles import CATALOGS, Catalog, TitleMatch
from torrent_finder.resolvers.types import Work
from torrent_finder.search_errors import SearchError
from torrent_finder.ui import discovery


class TopicResolverTests(unittest.TestCase):
    def setUp(self):
        topics._anilist_topics.cache_clear()
        self.addCleanup(topics._anilist_topics.cache_clear)

    def test_phrase_matches_catalog_description_without_invented_topic(self):
        vocab = {"GenreCollection": ["Psychological"], "MediaTagCollection": [
            {"id": 96, "name": "Time Manipulation", "description": "Features time-traveling phenomena."},
            {"id": 2, "name": "Mahjong", "description": "Mahjong games."}]}
        with patch.object(topics.anilist, "_post", return_value=vocab) as post:
            self.assertEqual(topics.find_topics(CATALOGS[0], "time travel")[0].name, "Time Manipulation")
            self.assertEqual(topics.find_topics(CATALOGS[0], "nonexistent"), [])
            self.assertEqual(topics.find_topics(CATALOGS[0], "mahjong")[0].id, "2")
            self.assertEqual(post.call_count, 1)

    def test_failed_vocabulary_is_not_cached_or_reported_as_no_matches(self):
        with patch.object(topics.anilist, "_post", return_value=None) as post:
            for _ in range(2):
                with self.assertRaises(SearchError):
                    topics.find_topics(CATALOGS[0], "mahjong")
            self.assertEqual(post.call_count, 2)

    def test_anilist_requires_all_terms_and_discards_incidental_tags(self):
        node = {"id": 5671, "title": {"romaji": "Saki", "native": "咲-Saki-"},
                "genres": ["Sports"], "tags": [{"name": "Mahjong", "rank": 100}]}
        data = {"Page": {"pageInfo": {"hasNextPage": True}, "media": [
            node, dict(node, id=2, tags=[{"name": "Mahjong", "rank": 20}]),
            dict(node, id=3, genres=[])]}}
        with patch.object(topics.anilist, "_post", return_value=data) as post:
            matches, more = topics.discover(CATALOGS[0], [topics.Topic("tag", "1", "Mahjong"), topics.Topic("genre", "Sports", "Sports")])
        self.assertEqual([m.id for m in matches], ["5671"])
        self.assertIn("100%", matches[0].note)
        self.assertTrue(more)
        self.assertIn("minimumTagRank: 60", post.call_args.args[0])
        self.assertEqual(post.call_args.args[1]["genres"], ["Sports"])

    def test_tmdb_combines_keywords_and_genres_with_and_and_keeps_tv_type(self):
        catalog = Catalog("tv", "TV", ("movies",))
        with patch.object(topics.tmdb, "_get", return_value={"results": [
                {"id": 10, "name": "Example", "original_name": "Original", "first_air_date": "2020-01-01"}], "total_pages": 5}) as get:
            rows, more = topics.discover(catalog, [topics.Topic("keyword", "1", "time travel"),
                topics.Topic("keyword", "2", "mystery"), topics.Topic("genre", "9", "Drama")], page=3)
        self.assertFalse(more)
        self.assertEqual(rows[0].id, "tv/10")
        self.assertEqual(get.call_args.args[1]["with_keywords"], "1,2")
        self.assertEqual(get.call_args.args[1]["with_genres"], "9")

    def test_missing_credentials_does_not_contact_catalog(self):
        with patch("torrent_finder.resolvers.titles.credentials.get_credential", return_value=None), \
             patch.object(topics.igdb, "_post") as post:
            with self.assertRaises(SearchError):
                topics.find_topics(CATALOGS[3], "survival")
        post.assert_not_called()

    def test_malformed_catalog_responses_are_not_empty_matches(self):
        with patch.object(topics.tmdb, "_get", return_value={"unexpected": []}):
            with self.assertRaises(SearchError):
                topics.find_topics(Catalog("tv", "TV", ("movies",)), "Drama")
        with patch.object(topics.openlibrary, "_get", return_value={"error": "unavailable"}):
            with self.assertRaises(SearchError):
                topics.find_topics(CATALOGS[-1], "time travel")

    def test_igdb_coop_alias_and_bounded_multiquery(self):
        catalog = Catalog("games", "Games", ("games",))
        data = [{"name": kind, "result": [{"id": 2, "name": "Co-operative"}] if kind == "game_modes" else []}
                for kind in ("genres", "themes", "game_modes", "keywords")]
        with patch.object(topics.igdb, "_post", return_value=data) as post:
            found = topics.find_topics(catalog, "co-op")
        self.assertEqual(found[0].kind, "game_modes")
        self.assertEqual(post.call_args.args[0], "multiquery")
        self.assertIn('co-operative', post.call_args.args[1])
        self.assertEqual(post.call_args.args[1].count("limit 12"), 4)

    def test_igdb_survival_and_coop_are_both_required(self):
        catalog = Catalog("games", "Games", ("games",))
        with patch.object(topics.igdb, "_post", return_value=[{"id": 1, "name": "Example"}]) as post:
            topics.discover(catalog, [topics.Topic("themes", "21", "Survival"), topics.Topic("game_modes", "2", "Co-operative")])
        self.assertIn("themes = [21] & game_modes = [2]", post.call_args.args[1])

    def test_openlibrary_subject_lookup_is_not_a_title_search(self):
        with patch.object(topics.openlibrary, "_get", return_value={"name": "time travel", "work_count": 2}) as get:
            found = topics.find_topics(CATALOGS[-1], "time travel")
        self.assertEqual(get.call_args.args[0], "/subjects/time_travel.json")
        with patch.object(topics.openlibrary, "_get", return_value={"work_count": 30,
                "works": [{"key": "/works/OL1W", "title": "The Time Machine", "authors": [{"name": "H. G. Wells"}]}]}) as get:
            matches, more = topics.discover(CATALOGS[-1], found, page=2)
        self.assertEqual(get.call_args.args[1]["offset"], 12)
        self.assertIn("H. G. Wells", matches[0].work.subtitle)
        self.assertTrue(more)
        with self.assertRaises(ValueError):
            topics.discover(CATALOGS[-1], found * 2)

    def test_combined_scope_excludes_incompatible_sources_and_preserves_original(self):
        original = CombinedProvider([get_provider(s) for s in ("anime", "games", "software", "rutracker")])
        original.restore({"selected": ["anime", "games", "software", "rutracker"]})
        scoped = topics.scope_for(original, CATALOGS[0])
        self.assertEqual(scoped.selected_slugs, {"anime", "rutracker"})
        self.assertEqual(original.selected_slugs, {"anime", "games", "software", "rutracker"})
        self.assertEqual(topics.discovery_catalogs(get_provider("software")), [])

    def test_fanout_is_bounded_and_primary_names_precede_aliases(self):
        works = [TitleMatch("anime", str(i), Work(f"Primary {i}", alt_titles=tuple(f"Alias {i}-{j}" for j in range(10)))) for i in range(3)]
        queries, origins = topics.query_plan(works)
        self.assertEqual(len(queries), 6)
        self.assertEqual(queries[:2], ["Primary 0", "Alias 0-0"])
        self.assertEqual(origins["Alias 2-0"], "Primary 2")
        with self.assertRaises(ValueError):
            topics.query_plan(works + works)
        with self.assertRaises(ValueError):
            topics.discover(CATALOGS[0], [topics.Topic("tag", "1", "Mahjong")], page=4)

    def test_work_selection_review_and_history_use_exact_names(self):
        work = TitleMatch("anime", "5671", Work("Saki", alt_titles=("咲-Saki-",)), "Mahjong 100%")
        provider = SimpleNamespace(slug="anime", name="Anime", active_presets=[])
        def select(items, **kwargs):
            if kwargs["title"].startswith("Matching"):
                items[0].toggled = True
                return next(i for i, item in enumerate(items) if item.value == "search")
            return next(i for i, item in enumerate(items) if item.value == "search")
        run = lambda fn, *args, **kwargs: (False, fn())
        with patch.object(discovery, "_lookup", return_value=([work], False)), \
             patch.object(discovery, "arrow_select", side_effect=select), \
             patch.object(discovery, "_run_cancellable", side_effect=run), \
             patch.object(discovery, "search_many", return_value=[]) as search, \
             patch("torrent_finder.state.add_history_entry") as history, \
             patch("torrent_finder.stats.record_search"):
            self.assertEqual(discovery._browse_works(provider, CATALOGS[0], [topics.Topic("tag", "1", "Mahjong")],
                             None, lambda *a, **k: "next"), "next")
        self.assertEqual(search.call_args.args[1], ["Saki", "咲-Saki-"])
        self.assertEqual(history.call_args.kwargs["queries"], ["Saki", "咲-Saki-"])
        self.assertEqual(provider.last_queries, ["Saki", "咲-Saki-"])


if __name__ == "__main__":
    unittest.main()
