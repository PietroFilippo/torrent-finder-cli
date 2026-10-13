"""Flow display translates without changing routing, metadata or saved names."""

import io
import json
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import isolation  # noqa: F401 — redirect persistence before importing app modules
from isolation import isolate_store
from rich.console import Console

from torrent_finder import acquisition, apibay_cache, i18n, madokami, main
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.result_details import detail_lines
from torrent_finder.search_result import SearchResult
from torrent_finder.ui import bookmarks, credentials


class FlowLanguageTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)
        self.addCleanup(i18n.use, "en")

    def test_results_keep_the_no_presets_sentinel_but_translate_active_filters(self):
        provider = MovieProvider()
        provider.active_presets = []
        provider.preferred_presets = []
        i18n.use("pt-BR")
        with patch.object(main, "clear_screen"), patch.object(main, "interactive_select", return_value=None) as select:
            self.assertEqual(main.browse_results(provider, []), "back")
            self.assertEqual(select.call_args.kwargs["search_summary"], "No presets")
            provider.active_presets = [next(p for p in provider.presets if p.name == "With Subtitles")]
            self.assertEqual(main.browse_results(provider, []), "back")
            self.assertEqual(select.call_args.kwargs["search_summary"], provider.filter_summary_label())
            self.assertIn("legendas", select.call_args.kwargs["search_summary"].lower())
            self.assertIn("With Subtitles", provider.filter_summary())
            self.assertEqual(select.call_args.kwargs["heading"], "Filmes e séries")

    def test_compare_bookmarks_keeps_its_summary_override(self):
        i18n.use("pt-BR")
        entry = {"result": {"name": "Back", "info_hash": "a" * 40}, "fetched_at": "yesterday"}
        with patch.object(bookmarks, "bookmark_menu", side_effect=[("compare", [entry]), None]), \
             patch.object(main, "clear_screen"), patch.object(main, "interactive_select", return_value=None) as select:
            main._bookmarks_flow()
        self.assertEqual(select.call_args.kwargs["search_summary"],
                         "Favoritos salvos; os metadados podem estar desatualizados")
        self.assertEqual(entry["result"]["name"], "Back")

    def test_madokami_names_translate_only_in_bookmark_and_detail_display(self):
        path = "/Manga/O/ON/ONE_/One%20Piece"
        row = SearchResult(name=madokami.display_name(path), handle={"mdk_path": path})
        entry = {"kind": "result", "name": row.name, "result": row.to_dict()}
        for language in ("pt-BR", "qps", "en"):
            i18n.use(language)
            with self.subTest(language=language):
                shown = madokami.localized_display_name(path)
                self.assertEqual(bookmarks._display_name(entry), shown)
                self.assertEqual(detail_lines(row)[0], i18n.t("Full name: {name}", name=shown))
                self.assertEqual(entry["name"], "One Piece [series folder]")
                self.assertEqual(row.name, entry["name"])
                self.assertEqual(row["mdk_path"], path)
                self.assertEqual(bookmarks._display_name({"kind": "search", "name": "Back"}), "Back")

    def test_cache_and_result_defaults_remain_english(self):
        # Importing isolation redirects the cache to the test sandbox.
        for language in ("pt-BR", "qps", "en"):
            i18n.use(language)
            row = SearchResult(info_hash="a" * 40, source="Apibay")
            self.assertEqual(row.name, "Unknown")
            row["name"] = None
            self.assertEqual(row.name, "Unknown")
            apibay_cache.store("movies", "Back", [row], now=123)
            saved = apibay_cache.load("movies", "Back")[0]
            self.assertEqual((saved.name, saved.source), ("Unknown", "Apibay"))
            persisted = json.loads(Path(apibay_cache.CACHE_PATH).read_text(encoding="utf-8"))
            self.assertIn('"source": "Apibay"', json.dumps(persisted))

    def test_batch_uses_note_label_without_changing_outcome_or_stats(self):
        i18n.use("pt-BR")
        outcome = acquisition.BatchItemOutcome(True, note="Kept archive packed")
        adapter = SimpleNamespace(has_magnet=True, batch_item=Mock(return_value=outcome))
        row = SearchResult(name="Back", info_hash="a" * 40, seeders=3)
        provider = MovieProvider()
        with patch.object(acquisition, "for_result", return_value=adapter), \
             patch.object(acquisition.BatchItemOutcome, "note_label", return_value="Arquivo mantido compactado") as label, \
             patch.object(acquisition, "batch_download_dir", return_value=""), \
             patch.object(main, "start_esc_listener", return_value=threading.Event()), \
             patch.object(main.console, "status", return_value=MagicMock()), \
             patch.object(main, "record_torrent_picked") as stats, patch.object(main, "record_magnet_dispatch"), \
             patch.object(main, "download_complete_prompt", return_value="next") as prompt:
            self.assertEqual(main._batch_handoff_run(provider, [row], [0]), ("next", []))
        label.assert_called_once_with()
        self.assertIn("Arquivo mantido compactado", prompt.call_args.kwargs["summary"])
        self.assertEqual(outcome.note, "Kept archive packed")
        stats.assert_called_once_with(provider.slug, 3)

    def test_credential_verification_labels_cover_both_sources_and_escape_values(self):
        i18n.use("pt-BR")
        for credential_id in ("opensubtitles", "addic7ed", "jimaku"):
            message = "Couldn't verify (Gateway [/x])"
            meta = SimpleNamespace(id=credential_id, display_name=lambda: "Service", save=Mock(),
                                   effective_values=lambda values: values, missing_required=lambda values: [],
                                   verify=lambda values: (None, message))
            output = io.StringIO()
            with self.subTest(credential_id=credential_id), \
                 patch.object(credentials, "console", Console(file=output, width=120, color_system=None)), \
                 patch.object(credentials.readchar, "readkey", return_value="x"):
                self.assertTrue(credentials._finalize_credentials_save(meta, {"key": "secret"}))
            self.assertIn(i18n.t("Couldn't verify ({error})", error="Gateway [/x]"), output.getvalue())
            meta.save.assert_called_once_with({"key": "secret"})

    def test_counted_announcements_and_clipboard_summary_have_portuguese_plural_forms(self):
        i18n.use("pt-BR")
        for n, noun in ((0, "resultados"), (1, "resultado"), (2, "resultados")):
            self.assertEqual(i18n.tn("You find {n} result for {queries}.", "You find {n} results for {queries}.",
                                    n, queries="Back"), f"Você encontra {n} {noun} para Back.")
        with patch.object(main, "_magnet_for", return_value="magnet:?xt=fixture"), \
             patch.object(main, "_copy_to_clipboard", return_value=True), \
             patch.object(main.readchar, "readkey", return_value="x"), patch.object(main, "clear_screen"), \
             patch.object(main.console, "status", return_value=nullcontext()), patch.object(main.console, "print") as printed:
            main._batch_copy_magnets(MovieProvider(), [{}], [0])
        self.assertIn("1 link magnet copiado", printed.call_args_list[0].args[0])


if __name__ == "__main__":
    unittest.main()
