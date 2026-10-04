import io
import unittest
from unittest.mock import patch

from rich.console import Console

from torrent_finder import main, settings_backup, state, store
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.combined_provider import CombinedProvider
from torrent_finder.providers.manga_provider import MangaProvider
from torrent_finder.resolvers import titles
from torrent_finder.resolvers.types import Work
from torrent_finder.search_errors import SearchError
from torrent_finder.ui import titles as title_ui
from torrent_finder.ui import selector
from isolation import isolate_store


class TitleSearchTests(unittest.TestCase):
    def catalog(self, key):
        return next(c for c in titles.CATALOGS if c.key == key)

    def test_anilist_identification_preserves_native_synonyms_and_sequel_identity(self):
        nodes = [dict(id=1, title=dict(romaji="Saki", english="SAKI", native="咲"),
                      synonyms=["Saki", "咲-Saki-"], startDate={"year": 2009}, format="TV"),
                 dict(id=2, title=dict(romaji="Saki", native="咲"), startDate={"year": 2014}, format="TV")]
        with patch.object(titles.anilist, "_post", return_value={"Page": {"media": nodes, "pageInfo": {"hasNextPage": True}}}) as request:
            matches, more = titles.search_titles(self.catalog("anime"), "Saki", 2)
        self.assertEqual(matches[0].work.alt_titles, ("咲", "咲-Saki-"))
        self.assertNotEqual(matches[0].id, matches[1].id)
        self.assertNotEqual(matches[0].work.year, matches[1].work.year)
        self.assertTrue(more)
        self.assertEqual(request.call_args.args[1], {"search": "Saki", "type": "ANIME", "page": 2})

    def test_empty_catalog_and_failed_catalog_are_distinct(self):
        with patch.object(titles.anilist, "_post", return_value=None):
            with self.assertRaisesRegex(SearchError, "unavailable"):
                titles.search_titles(self.catalog("anime"), "Saki")
        with patch.object(titles.anilist, "_post", return_value={"Page": {"media": []}}):
            self.assertEqual(titles.search_titles(self.catalog("anime"), "Missing"), ([], False))

    def test_tmdb_filters_people_and_loads_aliases_only_for_picked_work(self):
        data = {"results": [{"media_type": "person", "id": 7, "name": "Example"},
                            {"media_type": "movie", "id": 8, "title": "English", "original_title": "Original", "release_date": "2001-02-03"},
                            {"media_type": "tv", "id": 9, "name": "English", "first_air_date": "2020-01-01"}], "total_pages": 8}
        with patch.object(titles.credentials, "get_credential", return_value="dummy"), \
             patch.object(titles.tmdb, "_get", return_value=data) as get:
            matches, more = titles.search_titles(self.catalog("movies"), "English")
            self.assertEqual(get.call_count, 1)
            get.return_value = {"titles": [{"iso_3166_1": "JP", "title": "日本"}, {"iso_3166_1": "BR", "title": "Português"}]}
            chosen = titles.resolve_names(matches[0])
        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0].id, "movie/8")
        self.assertEqual(matches[1].id, "tv/9")
        self.assertTrue(more)
        self.assertEqual(chosen.work.alt_titles, ("Original", "Português", "日本"))
        self.assertEqual(get.call_args.args[0], "/movie/8/alternative_titles")

    def test_missing_credentials_never_send_catalog_request(self):
        with patch.object(titles.credentials, "get_credential", return_value=None), patch.object(titles.tmdb, "_get") as get:
            with self.assertRaisesRegex(SearchError, "TMDB_API_KEY"):
                titles.search_titles(self.catalog("movies"), "Example")
        get.assert_not_called()

    def test_igdb_keeps_alternative_names_year_platform_and_escapes_search(self):
        with patch.object(titles.credentials, "get_credential", return_value="dummy"), \
             patch.object(titles.igdb, "_post", return_value=[dict(id=3, name="Game", alternative_names=[{"name": "別名"}],
                    first_release_date=946684800, platforms=[{"name": "PC"}], version_title="Remastered")]) as post:
            matches, more = titles.search_titles(self.catalog("games"), 'A "quoted" game')
        self.assertEqual(matches[0].work.alt_titles, ("別名",))
        self.assertIn("Remastered", matches[0].work.subtitle)
        self.assertEqual(matches[0].work.year, 2000)
        self.assertIn('search "A \\"quoted\\" game"', post.call_args.args[1])
        self.assertFalse(more)

    def test_openlibrary_disambiguates_by_author_and_work_id(self):
        with patch.object(titles.openlibrary, "_get", return_value={"numFound": 1, "docs": [
            dict(key="/works/OL123W", title="Book", author_name=["Writer"], first_publish_year=1901)]}) as get:
            matches, more = titles.search_titles(self.catalog("books"), "Book")
            get.return_value = {"alternative_titles": ["Alternate"]}
            match = titles.resolve_names(matches[0])
        self.assertIn("Writer", match.work.subtitle)
        self.assertEqual(match.work.alt_titles, ("Alternate",))
        self.assertFalse(more)

    def test_unavailable_extra_names_preserves_confirmable_primary(self):
        match = titles.TitleMatch("movies", "movie/1", Work("Title", ("Original",)))
        with patch.object(titles.tmdb, "_get", return_value=None):
            resolved = titles.resolve_names(match)
        self.assertEqual(resolved.work, match.work)
        self.assertIn("could not", resolved.note)

    def test_catalog_pages_are_bounded(self):
        with self.assertRaises(ValueError):
            titles.search_titles(self.catalog("anime"), "Example", 4)

    def test_catalog_choices_follow_combined_selected_categories(self):
        provider = CombinedProvider([AnimeProvider(), MangaProvider()])
        provider.restore({"selected": ["manga"]})
        self.assertEqual([c.key for c in titles.catalogs_for(provider)], ["manga"])

    def test_name_picker_bounds_queries_and_cancels_without_search(self):
        match = titles.TitleMatch("anime", "1", Work("Title", tuple(f"Alt {i}" for i in range(12))))
        def choose(items, **kwargs):
            return len(items) - 2
        with patch.object(title_ui, "arrow_select", side_effect=choose):
            names = title_ui.pick_names(match)
        self.assertEqual(len(names), 6)
        self.assertEqual(names[0], "Title")
        with patch.object(title_ui, "arrow_select", return_value=None):
            self.assertIsNone(title_ui.pick_names(match))

    def test_name_picker_space_deselects_before_confirming(self):
        import readchar
        match = titles.TitleMatch("anime", "1", Work("Primary", ("English", "Native")))
        sized = Console(file=io.StringIO(), width=40, height=16)
        with patch.object(selector, "console", sized), patch.object(selector.sys, "stdout", io.StringIO()), \
             patch.object(selector.readchar, "readkey", side_effect=[readchar.key.DOWN, readchar.key.DOWN, " ", "w"]):
            names = title_ui.pick_names(match)
        self.assertEqual(names, ["Primary", "English"])

    def test_alias_history_replay_and_backup_keep_exact_chosen_names(self):
        isolate_store(self)
        state.add_history_entry("Title", "anime", queries=["Title", "別名"])
        state.add_history_entry("Title", "anime")
        history = state.load_history()
        self.assertEqual(len(history), 2)
        entry = history[1]
        _, facet, queries = main._history_pick(entry)
        self.assertIsNone(facet)
        self.assertEqual(queries, ["Title", "別名"])
        settings_backup.validate_payload({"history": history})
        self.assertEqual(len(store._merge_history([(0, {"history": history})])), 2)
        entry["queries"] = ["name"] * 7
        with self.assertRaises(ValueError):
            settings_backup.validate_payload({"history": [entry]})

    def test_diagnostic_rows_and_long_detail_view_fit_compact_terminal(self):
        from torrent_finder.ui.search_diagnostics import read_details
        captured = []
        def render(items, **kwargs):
            sized = Console(file=io.StringIO(), width=40, height=16)
            with patch.object(selector, "console", sized):
                for index in range(len(items)):
                    panel = selector._build_panel(items, index, kwargs["title"], False, kwargs["footer"])
                    lines = sized.render_lines(panel, sized.options)
                    captured.append(len(lines))
                    self.assertLessEqual(len(lines), 16)  # the frame carries its own header line
            return None
        sized = Console(file=io.StringIO(), width=40, height=16)
        with patch("torrent_finder.ui.search_diagnostics.console", sized), \
             patch("torrent_finder.ui.search_diagnostics.arrow_select", side_effect=render):
            read_details("Very long query " * 35 + "\nRequire PT-BR: removed 42\nRequest timed out.")
        self.assertGreater(len(captured), 10)


if __name__ == "__main__":
    unittest.main()
