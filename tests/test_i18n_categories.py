"""Categories localize display without changing persistence, queries or service data."""

import unittest
from unittest.mock import patch

import isolation  # noqa: F401 — redirect settings before importing application state
from isolation import isolate_store, restart_store
from torrent_finder import bookmarks, i18n
from torrent_finder.name_rules import NameRules
from torrent_finder.providers import (PROVIDERS, GAMES_GROUP, SOFTWARE_GROUP, MANGA_GROUP,
                                      creator_facet_choices, provider_cli_choices, display_name_for)
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.base import filter_reason_label
from torrent_finder.providers.combined_provider import (CombinedProvider, provider_label,
                                                       provider_display_label)
from torrent_finder.providers.game_provider import GameProvider
from torrent_finder.providers.manga_provider import MangaProvider
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.resolvers import anilist, topics, tmdb
from torrent_finder.resolvers.titles import CATALOGS, Catalog, TitleMatch
from torrent_finder.resolvers.types import Entity, Work
from torrent_finder.search_errors import SearchError
from torrent_finder.search_profiles import ProfileLibrary, profile_label
from torrent_finder.search_result import SearchResult
from torrent_finder.state import apply_provider_state, provider_snapshot
from torrent_finder.ui import combined, creator, discovery, titles


class CategoriesLanguageTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)
        self.addCleanup(i18n.use, "en")

    def test_existing_metadata_changes_language_at_draw_time(self):
        movie, manga = MovieProvider(), MangaProvider()
        labels = [movie.label, GAMES_GROUP.label, SOFTWARE_GROUP.label, MANGA_GROUP.label]
        i18n.use("pt-BR")
        self.assertEqual([movie.label, GAMES_GROUP.label, SOFTWARE_GROUP.label, MANGA_GROUP.label],
                         ["Filmes e séries", "Jogos", "Programas", "Mangá"])
        self.assertEqual(movie.name, "Movies & Series")
        self.assertEqual(provider_label(manga), "Manga · General")
        self.assertEqual(provider_display_label(manga), "Mangá · Geral")
        self.assertEqual(display_name_for("manga"), "Mangá · Geral")
        self.assertEqual(display_name_for("Unknown custom category"), "Unknown custom category")
        i18n.use("en")
        self.assertEqual([movie.label, GAMES_GROUP.label, SOFTWARE_GROUP.label, MANGA_GROUP.label], labels)

    def test_initializing_providers_does_not_translate(self):
        with patch.object(i18n, "_entry", side_effect=AssertionError("eager translation")):
            for template in PROVIDERS:
                if not getattr(template, "is_combined", False):
                    type(template)()

    def test_cli_and_creator_keys_do_not_depend_on_language(self):
        choices, facets = provider_cli_choices(), creator_facet_choices()
        i18n.use("pt-BR")
        self.assertEqual(provider_cli_choices(), choices)
        self.assertEqual(creator_facet_choices(), facets)
        director = MovieProvider().creator_facets[0]
        self.assertEqual((director.key, director.label, i18n.t(director.label)),
                         ("director", "Director", "Diretor"))

    def test_preset_snapshot_round_trip_uses_english_names_and_engine_modes(self):
        provider = MangaProvider()
        provider.active_presets = [next(p for p in provider.presets if p.name == "Portuguese")]
        provider.preferred_presets = [next(p for p in provider.presets if p.name == "Complete / Full")]
        saved = provider_snapshot(provider)
        i18n.use("pt-BR")
        self.assertEqual(provider.active_presets[0].label, "Português")
        self.assertEqual(provider.preferred_presets[0].label, "Completo")
        self.assertEqual(provider_snapshot(provider), saved)
        restored = MangaProvider()
        apply_provider_state(restored, saved)
        self.assertEqual(provider_snapshot(restored), saved)
        self.assertIn("Portuguese", saved["active_presets"])

    def test_typed_presets_and_matching_words_remain_search_data(self):
        provider = MangaProvider()
        english = provider.typed_split("Berserk português")
        i18n.use("pt-BR")
        self.assertEqual(provider.typed_split("Berserk português"), english)
        self.assertEqual(english[1].name, "Portuguese")
        provider.active_presets = [english[1]]
        self.assertIn("Nyaa (Non-English)", provider._required_engine_names())
        self.assertTrue(english[1].config.name_predicate("Berserk português"))
        movie = MovieProvider()
        movie.active_presets = [next(p for p in movie.presets if p.name == "Dublado (PT-BR)")]
        self.assertEqual(movie.active_presets[0].label, "Dublado (PT-BR)")
        self.assertEqual(movie.active_presets[0].query_terms, ("pt-br", "dublado"))

    def test_no_presets_sentinel_and_formatted_summaries_keep_old_contract(self):
        movie = MovieProvider()
        i18n.use("pt-BR")
        self.assertEqual(movie.filter_summary(), "No presets")
        self.assertEqual(movie.filter_summary_label(), "Sem filtros")
        movie.active_presets = [next(p for p in movie.presets if p.name == "With Subtitles")]
        movie.name_rules = NameRules(all_words="Back")
        self.assertEqual(movie.filter_summary(), "Names: All: Back; Require: With Subtitles")
        self.assertEqual(movie.filter_summary_label(), "Nomes: Todas: Back; Exigir: Com legendas")

    def test_name_rules_summary_does_not_translate_rule_contents(self):
        rules = NameRules(all_words="Back", exclude_words="Games")
        original = rules.snapshot()
        i18n.use("pt-BR")
        self.assertEqual(rules.summary(), "All: Back; Exclude: Games")
        self.assertEqual(rules.summary_label(), "Todas: Back; Excluir: Games")
        self.assertEqual(rules.snapshot(), original)

    def test_filter_reasons_are_stable_and_have_separate_display_labels(self):
        movie = MovieProvider()
        movie.active_presets = [next(p for p in movie.presets if p.name == "With Subtitles")]
        row = SearchResult(name="Example 1080p", info_hash="a" * 40, source="Fixture")
        i18n.use("pt-BR")
        kept, removed = movie.filter_with_reasons([row])
        self.assertEqual(kept, [])
        self.assertEqual(removed, [("Require With Subtitles", 1)])
        self.assertEqual(filter_reason_label(removed[0][0]), "Exigir Com legendas")
        self.assertEqual(filter_reason_label("Provider defaults"), "Padrões da categoria")
        self.assertEqual(filter_reason_label("Custom reason"), "Custom reason")

    def test_bookmarks_keep_english_qualified_provider_labels(self):
        i18n.use("pt-BR")
        bookmarks.save_results(GameProvider(), [dict(name="Back", source="Apibay", info_hash="a" * 40)])
        result = bookmarks.entries()[0]["result"]
        self.assertEqual(result["provider_label"], "Games · General")
        self.assertEqual(result["name"], "Back")

    def test_profile_names_persist_in_english_and_user_names_are_never_translated(self):
        i18n.use("pt-BR")
        provider = CombinedProvider([MovieProvider()])
        provider.save_profile()
        restart_store()
        library = ProfileLibrary.load()
        self.assertEqual(library.current["name"], "Default")
        self.assertEqual(profile_label(library.current), "Padrão")
        for name in ("Back", "Games", "Default", "History search"):
            self.assertEqual(profile_label({"id": "custom", "name": name}), name)
        library.rename("default", "Back")
        self.assertEqual(profile_label(library.current), "Back")

    def test_history_profiles_and_combined_summary_separate_identity(self):
        provider = CombinedProvider([MovieProvider()])
        provider.restore_history({"selected": ["movies"]})
        original = provider.summary()
        i18n.use("pt-BR")
        self.assertEqual(provider.summary(), original)
        self.assertEqual(provider.profile_name, "History search (unsaved)")
        self.assertEqual(provider.profile_label, "Busca do histórico (não salva)")
        self.assertEqual(provider.summary_label()[0], "Filmes e séries")
        self.assertIn("0 regras de nome", provider.filter_summary_label())
        library = provider.profile_draft()
        self.assertEqual(library.current["name"], "History search")

    def test_nyaa_selection_identity_and_display_are_separate(self):
        anime = AnimeProvider()
        before = provider_snapshot(anime)
        i18n.use("pt-BR")
        self.assertEqual(anime.nyaa_category, "1_2")
        self.assertEqual(anime.nyaa_categories["1_2"], "English-translated")
        self.assertIn("Traduzido para inglês", anime.filter_summary_label())
        self.assertEqual(provider_snapshot(anime), before)

    def test_catalog_topics_keep_the_service_vocabulary(self):
        topics._anilist_topics.cache_clear()
        self.addCleanup(topics._anilist_topics.cache_clear)
        i18n.use("pt-BR")
        data = {"GenreCollection": ["Action"], "MediaTagCollection": []}
        with patch.object(anilist, "_post", return_value=data):
            found = topics.find_topics(CATALOGS[0], "Action")
        self.assertEqual((found[0].kind, found[0].name), ("genre", "Action"))
        self.assertEqual(topics.kind_label(found[0].kind), "gênero")

    def test_resolver_errors_are_translated_without_changing_credentials(self):
        i18n.use("pt-BR")
        catalog = Catalog("movies", "Movies", ("movies",), ("TMDB_API_KEY",))
        with patch.object(Catalog, "missing_credentials", return_value=("TMDB_API_KEY",)):
            with self.assertRaisesRegex(SearchError, "Configure TMDB_API_KEY em Credenciais"):
                topics.find_topics(catalog, "Action")

    def test_creator_metadata_plural_and_names_are_kept(self):
        i18n.use("pt-BR")
        def get(path, params=None):
            if path == "/search/company":
                return {"results": [{"id": 1, "name": "Back"}, {"id": 2, "name": "Games"}]}
            return {"total_results": int(params["with_companies"])}
        with patch.object(tmdb, "_get", side_effect=get):
            entities = tmdb.company_search("Back")
        self.assertEqual([(e.name, e.detail) for e in entities], [("Games", "2 filmes"), ("Back", "1 filme")])

    def test_discovery_does_not_translate_service_titles_or_shadow_t(self):
        i18n.use("pt-BR")
        topic = topics.Topic("genre", "1", "Action")
        with patch.object(discovery, "arrow_select", return_value=None) as select:
            discovery._choose_topics(CATALOGS[0], [topic])
        row = select.call_args.args[0][0]
        self.assertEqual((row.label, row.hint, row.value), ("Remover: Action", "gênero", topic))

    def test_manual_title_picker_preserves_query_words(self):
        i18n.use("pt-BR")
        match = TitleMatch("manual", "", Work("Back", alt_titles=("Games",)))
        with patch.object(titles, "arrow_select", return_value=3) as select:
            self.assertEqual(titles.pick_names(match), ["Back", "Games"])
        self.assertEqual(select.call_args.kwargs["title"], "Nomes para buscar (até 6)")

    def test_combined_menu_displays_translated_metadata_but_keeps_selection_slugs(self):
        i18n.use("pt-BR")
        draft = CombinedProvider([GameProvider(), MangaProvider()])
        draft.restore({"selected": ["games"]})
        with patch.object(combined, "arrow_select", return_value=None) as select:
            combined._choose_providers(draft)
        rows = select.call_args.args[0]
        self.assertEqual([(r.label, r.value) for r in rows[:2]],
                         [("Jogos · Geral", "games"), ("Mangá · Geral", "manga")])

    def test_creator_input_uses_translated_facets_and_preserves_typed_name(self):
        i18n.use("pt-BR")
        provider = MovieProvider()
        with patch.object(creator, "input_screen", return_value=lambda: None) as screen, \
             patch.object(creator, "get_query_with_shortcut", return_value="Back"):
            self.assertEqual(creator._name_input(provider, provider.creator_facets[0]), "Back")
        self.assertEqual(screen.call_args.args[0], "Filmes e séries › buscar por diretor")

    def test_creator_history_keeps_english_role_and_original_name(self):
        i18n.use("pt-BR")
        provider = MovieProvider()
        work = Work("Back")
        results = [SearchResult(name="Back", source="Fixture", info_hash="a" * 40)]
        replies = [(False, [Entity("1", "Back")]), (False, ([work], False)), (False, results)]
        with patch.object(creator, "_run_cancellable", side_effect=replies), \
             patch.object(creator, "_works_select_prompt", return_value=("confirm", {"Back"})), \
             patch.object(creator, "add_history_entry") as history, \
             patch.object(creator, "record_creator_search"):
            result = creator.creator_search_flow(provider, None, provider.creator_facets[0],
                                                 lambda *_: "next", initial_name="Back")
        self.assertEqual(result, "next")
        history.assert_called_once_with("Director: Back", "movies", [],
                                        kind="creator", facet="director", name="Back")

    def test_discovery_history_stays_english_while_result_note_is_translated(self):
        i18n.use("pt-BR")
        provider = AnimeProvider()
        match = TitleMatch("anime", "1", Work("Back"))
        criteria = [topics.Topic("genre", "Action", "Action")]
        notes = []

        def select(items, **kwargs):
            items[0].toggled = True
            return next(i for i, item in enumerate(items) if item.value == "search")

        def browse(provider, results, *, note):
            notes.append(note)
            return "next"

        with patch.object(discovery, "_lookup", return_value=([match], False)), \
             patch.object(discovery, "arrow_select", side_effect=select), \
             patch.object(discovery, "_run_cancellable", return_value=(False, [])), \
             patch("torrent_finder.state.add_history_entry") as history, \
             patch("torrent_finder.stats.record_search"):
            self.assertEqual(discovery._browse_works(provider, CATALOGS[0], criteria, None, browse), "next")
        history.assert_called_once_with("Topic discovery: Action", "anime", [], queries=["Back"])
        self.assertTrue(notes[0].startswith("Descoberta por tema: Action."))


if __name__ == "__main__":
    unittest.main()
