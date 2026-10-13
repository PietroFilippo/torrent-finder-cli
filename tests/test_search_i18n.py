"""Search display language never changes matching, pagination or saved identities."""

from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import isolation  # noqa: F401
from isolation import isolate_store
from torrent_finder import bookmarks, i18n
from torrent_finder.filters import FilterConfig, FilterPreset
from torrent_finder.providers.base import SearchEngine
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.result_details import detail_lines, release_tags, tag_label, tag_matches
from torrent_finder.result_view import SORT_ORDERS, match_mode_label, ranking_notes, result_indices, sort_label
from torrent_finder.search_diagnostics import Diagnostic, RequestTrace, observe_response, status_label
from torrent_finder.search_errors import login_required
from torrent_finder.search_result import SearchResult
from torrent_finder.search_session import MAX_PAGE, SearchSession
from torrent_finder.ui import bookmarks as bookmark_ui, result_filters, search_diagnostics as screen


class SearchLanguageTests(unittest.TestCase):
    def setUp(self):
        i18n.use("pt-BR")

    def test_sort_keys_and_indexes_stay_english_while_labels_change(self):
        rows = [{"name": "Dune 2024 1080p", "seeders": 1, "size": 20, "uploaded_at": 20},
                {"name": "Dune 2021 720p", "seeders": 10, "size": 10, "uploaded_at": 10}]
        expected = {"relevance": [0, 1], "seeds": [1, 0], "newest": [0, 1], "name": [1, 0], "size": [0, 1]}
        self.assertEqual(set(SORT_ORDERS), set(expected))
        for order, indexes in expected.items():
            self.assertEqual(result_indices(rows, "Dune", "contains", order), indexes)
        self.assertEqual(SORT_ORDERS["seeds"], "Most seeders")
        self.assertEqual(sort_label("seeds"), "Mais seeds")
        self.assertEqual([match_mode_label(mode) for mode in ("contains", "title", "filename")],
                         ["Contém", "Título", "Nome do arquivo"])
        self.assertEqual(sort_label("custom"), "custom")

    def test_sort_selector_returns_the_key_and_draws_translated_labels(self):
        with patch.object(result_filters, "arrow_select", return_value=1) as select:
            self.assertEqual(result_filters.choose_result_sort("name"), "seeds")
        items = select.call_args.args[0]
        self.assertEqual((items[1].label, items[1].value), ("Mais seeds", "seeds"))
        self.assertEqual(items[3].hint, "ativo")

    def test_refinement_returns_matching_codes_and_original_query(self):
        with patch.object(result_filters, "arrow_select", side_effect=[1, 9]), \
                patch("torrent_finder.ui.prompts.get_query_with_shortcut", return_value="Dune"):
            self.assertEqual(result_filters.refine_results("Dune", "contains", "seeds"),
                             ("Dune", "title", "seeds"))

    def test_release_tags_keep_matching_identities_until_display(self):
        name = "[FLUX] Dune 2024 1080p WEB-DL Dual Audio Dublado PT-BR"
        tags = release_tags(name)
        i18n.use("en")
        self.assertEqual(release_tags(name), tags)
        i18n.use("pt-BR")
        self.assertIn("PT-BR audio", tags)
        self.assertIn("Dual audio", tags)
        self.assertTrue(tag_matches("PT-BR audio", ["Dublado (PT-BR)"]))
        self.assertEqual(tag_label("PT-BR audio"), "áudio PT-BR")
        self.assertEqual(tag_label("group FLUX"), "grupo FLUX")
        self.assertEqual(tag_label("WEB-DL"), "WEB-DL")

    def test_ranking_translates_reason_and_keeps_preferred_names(self):
        provider = MovieProvider()
        provider.preferred_presets = [FilterPreset("PT-BR audio", FilterConfig(quality=["1080p"]))]
        reason, preferred = ranking_notes(provider, ["Dune"])(
            SearchResult(name="Dune 2024 1080p WEB-DL", seeders=10))
        self.assertEqual(preferred, ("PT-BR audio",))
        self.assertEqual(reason, "título exato, prefere áudio PT-BR")

    def test_detail_lines_translate_labels_without_changing_listing_data(self):
        row = {"name": "[FLUX] Dune 2024 1080p English Dual Audio", "source": "Apibay",
               "page_url": "https://example.test/dune", "provider_label": "Movies & Series"}
        original = deepcopy(row)
        lines = detail_lines(row)
        self.assertEqual(lines[0], "Nome completo: " + row["name"])
        self.assertIn("Fonte: Apibay", lines)
        self.assertIn("Resultado: " + row["page_url"], lines)
        self.assertTrue(any("Tag de inglês" in line and "grupo de release: FLUX" in line for line in lines))
        self.assertEqual(row, original)

    def test_pagination_states_and_legacy_returns_are_language_independent(self):
        provider = MovieProvider()
        provider.engines = [SearchEngine("Fixture", "", lambda q: [], page_fn=lambda q, p: [])]
        session = SearchSession([provider], ["Dune: part two"])
        task = session.tasks[0]
        cases = [("results", True, 0, "next", 1), ("timeout", True, 0, "incomplete", 0),
                 ("auto", True, 0, "not_needed", 0), ("results", False, 0, "exhausted", 0),
                 ("results", True, MAX_PAGE, "limit", MAX_PAGE)]
        for diagnostic, more, page, expected, number in cases:
            task.diagnostic = replace(task.diagnostic, status=diagnostic)
            task.has_more, task.page = more, page
            states, legacy = session.page_states(), session.page_status()
            self.assertEqual((states[0].status, states[0].number), (expected, number))
            self.assertEqual(screen._pages(SimpleNamespace(page_status=lambda: legacy)), states)
            i18n.use("qps")
            self.assertEqual((session.page_states(), session.page_status()), (states, legacy))
            i18n.use("pt-BR")
        task.engine.page_fn = None
        self.assertEqual(session.page_states()[0].status, "unavailable")
        task.diagnostic = replace(task.diagnostic, status="off")
        self.assertEqual(session.page_states(), ())

    def test_pagination_display_and_more_count_use_structured_statuses(self):
        provider = MovieProvider()
        provider.engines = [SearchEngine("Fixture", "", lambda q: [], page_fn=lambda q, p: [])]
        session = SearchSession([provider], ["Dune: part two"])
        session.tasks[0].diagnostic = replace(session.tasks[0].diagnostic, status="results")
        with patch.object(screen, "arrow_select", return_value=None) as select:
            screen.diagnostics_menu(session)
        items = select.call_args.args[0]
        self.assertEqual(next(item for item in items if item.value == "more").hint, "1 fonte com mais páginas")
        page = next(item for item in items if isinstance(item.value, tuple) and item.value[0] == "pages")
        self.assertEqual(page.hint, "próxima página 1")
        self.assertIn("Dune: part two", page.value[1])
        self.assertIn("próxima página: 1", page.value[1])

    def test_missing_login_is_classified_by_status_and_retryable_in_portuguese(self):
        with patch("torrent_finder.credentials.storage_problem", return_value=""):
            error = login_required("RuTracker")
        self.assertEqual(error.status, "missing_login")
        self.assertIn("sem login", str(error))
        provider = MovieProvider()
        provider.engines = [SearchEngine("RuTracker", "", Mock(side_effect=error))]
        results = SearchSession([provider], ["Dune"]).run()
        self.assertEqual(results.session.diagnostics[0].status, "missing_login")
        self.assertTrue(results.session.can_retry)
        self.assertEqual(results.notices, (str(error),))

    def test_diagnostic_codes_and_counts_stay_stable_while_evidence_translates(self):
        diagnostic = Diagnostic("Movies & Series", "Apibay", "Dune", 1, "timeout", raw=2, kept=1,
                                requests=1, cached=1, attempt=2)
        self.assertTrue(diagnostic.retryable)
        self.assertEqual(status_label(diagnostic.status), "tempo esgotado")
        text = diagnostic.describe()
        self.assertIn("1 solicitação", text)
        self.assertIn("1 resultado em cache", text)
        self.assertIn("tentativa 2", text)
        self.assertEqual((diagnostic.status, diagnostic.raw, diagnostic.kept), ("timeout", 2, 1))
        with RequestTrace() as trace:
            observe_response(SimpleNamespace(status_code=429))
        self.assertEqual(trace.failures, [("error", "A fonte retornou HTTP 429.")])

    def test_credentials_status_is_translated_only_in_the_diagnostics_row(self):
        spec = SimpleNamespace(id="rutracker", name="RuTracker", status=lambda: "not set")
        session = SimpleNamespace(can_retry=True, can_load_more=False, queries=["Dune"],
                                  page_states=lambda: (), diagnostics=[Diagnostic("Movies", "RuTracker", "Dune", 0, "missing_login")])
        with patch("torrent_finder.credential_registry.CREDENTIAL_REGISTRY", [spec]), \
                patch.object(screen, "arrow_select", return_value=None) as select:
            screen.diagnostics_menu(session)
        self.assertEqual(spec.status(), "not set")
        self.assertEqual(next(item for item in select.call_args.args[0] if item.label == "RuTracker").hint,
                         "não configurado")

    def test_bookmark_storage_keeps_names_profiles_and_refresh_status_in_english(self):
        path = isolate_store(self)
        provider = MovieProvider()
        provider.result_sort = "seeds"
        provider.last_queries = ["Back"]
        row = {"name": "Back", "source": "Apibay", "info_hash": "a" * 40}
        original = deepcopy(row)
        self.assertIn("Salvo nos favoritos", bookmarks.save_results(provider, [row]))
        saved = bookmarks.entries()[0]
        self.assertEqual((saved["name"], saved["queries"], saved["search_profile"]["result_sort"]),
                         ("Back", ["Back"], "seeds"))
        self.assertEqual(row, original)
        bookmarks.refresh(saved["id"], [row])
        self.assertEqual(bookmarks.entries()[0]["refresh_status"], "Listing found")
        self.assertIn("Resultado encontrado", bookmark_ui._description(bookmarks.entries()[0]))
        before = path.read_bytes()
        bookmarks.refresh_status_label("Listing found")
        self.assertEqual(path.read_bytes(), before)
        bookmarks.refresh(saved["id"], [])
        stored = json.loads(path.read_text(encoding="utf-8"))["bookmarks"][0]
        self.assertEqual(stored["refresh_status"], "Not returned by this search; saved listing retained")
        self.assertEqual(stored["result"]["name"], "Back")
        self.assertEqual(bookmarks.refresh_status_label("Back"), "Back")
        self.assertEqual(bookmarks.refresh_status_label("Not refreshed"), "Não atualizado")


if __name__ == "__main__":
    unittest.main()
