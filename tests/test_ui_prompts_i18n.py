"""Prompt translations keep acquisition, filter and credential identities stable."""

import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import isolation  # noqa: F401 — keep every screen away from real settings
from isolation import isolate_store
from rich.console import Console
from rich.markup import escape

from torrent_finder import i18n
from torrent_finder.name_rules import NameRules
from torrent_finder.providers import SOFTWARE_GROUP
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.combined_provider import CombinedProvider
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.providers.game_provider import GameProvider
from torrent_finder.result_view import sort_label
from torrent_finder.state import provider_snapshot
from torrent_finder.torrent_info import TorrentInfo, description_label, info_label
from torrent_finder.ui import prompts, selector, theme


class PromptLanguageTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)
        self.addCleanup(i18n.use, "en")

    def confirm(self, language, key, width=80, height=24):
        i18n.use(language)
        output = io.StringIO()
        screen = Console(file=output, width=width, height=height, color_system=None)
        with patch.object(prompts, "console", screen), \
             patch.object(selector, "_render", side_effect=lambda _, panel, **kw: screen.print(panel)), \
             patch.object(prompts.display, "enter_screen"), patch.object(prompts.display, "leave_screen"), \
             patch.object(prompts.readchar, "readkey", return_value=key):
            answer = prompts.confirm_prompt(i18n.t("Confirm"))
        return answer, output.getvalue()

    def test_confirm_accepts_brazilian_and_english_answers(self):
        for language, answers in (("pt-BR", ("s", "S", "sim", "SIM", "y", "Y", "yes", "YES")),
                                  ("en", ("y", "Y", "yes", "YES")), ("qps", ("y", "yes"))):
            for key in answers:
                with self.subTest(language=language, key=key):
                    self.assertTrue(self.confirm(language, key)[0])
        for language, answers in (("en", ("s", "sim", "n", "\x1b")),
                                  ("pt-BR", ("n", "não", "\x1b", "\r")), ("qps", ("s", "sim"))):
            for key in answers:
                with self.subTest(language=language, key=key):
                    self.assertFalse(self.confirm(language, key)[0])

    def test_confirm_shows_s_at_every_required_size(self):
        for width, height in ((40, 12), (80, 24), (137, 36), (200, 50)):
            with self.subTest(size=(width, height)):
                answer, rendered = self.confirm("pt-BR", "s", width, height)
                self.assertTrue(answer)
                self.assertIn("S confirmar", rendered)
                self.assertNotIn("Y confirmar", rendered)
                self.assertIn("Esc cancelar", rendered)

    def test_filter_save_and_cancel_keep_english_modes_and_preset_names(self):
        for language in ("pt-BR", "qps"):
            for save in (False, True):
                with self.subTest(language=language, save=save):
                    provider = MovieProvider()
                    before = provider_snapshot(provider)
                    saved = Mock()
                    i18n.use(language)

                    def choose(items, **kwargs):
                        for item in items:
                            if not isinstance(item.value, tuple):
                                continue
                            kind, obj = item.value
                            if kind == "engine":
                                self.assertEqual(set(item.toggle_states),
                                                 {"On", "Auto", "Off"} if obj.emergency_fallback else {"On", "Off"})
                                item.toggle_state = "Auto" if obj.emergency_fallback else "Off"
                                self.assertEqual(item.description, escape(i18n.t(obj.description)))
                            else:
                                self.assertEqual(item.toggle_states, ("Off", "Require", "Prefer"))
                                self.assertEqual(item.label, obj.label)
                                item.toggle_state = "Prefer"
                        return next(i for i, item in enumerate(items) if item.value == "confirm") if save else None

                    with patch.object(prompts, "arrow_select", side_effect=choose):
                        prompts.filter_menu(provider, on_save=saved)
                    if save:
                        self.assertEqual([e.mode for e in provider.engines], ["off", "auto", "off", "off", "off"])
                        self.assertEqual([p.name for p in provider.preferred_presets], [p.name for p in provider.presets])
                        saved.assert_called_once_with()
                    else:
                        self.assertEqual(provider_snapshot(provider), before)
                        saved.assert_not_called()

    def test_search_status_uses_display_helpers_without_changing_rules(self):
        provider = MovieProvider()
        preset = next(p for p in provider.presets if p.name == "With Subtitles")
        provider.active_presets = [preset]
        provider.name_rules = NameRules.restore({"all_words": "Back English"})
        before = provider_snapshot(provider)
        i18n.use("pt-BR")
        filters = prompts.filters_line(provider).plain
        self.assertIn("Exigir " + preset.label, filters)
        self.assertIn(provider.name_rules.summary_label(), filters)
        self.assertIn("Ctrl+F para alterar", filters)
        self.assertIn("Mecanismos", prompts.engines_line(provider).plain)
        self.assertEqual(provider_snapshot(provider), before)

    def test_combined_summary_uses_profile_label_but_preserves_custom_names(self):
        provider = CombinedProvider([MovieProvider(), AnimeProvider()])
        provider.restore({"selected": ["movies", "anime"]})
        before = provider.snapshot()
        i18n.use("pt-BR")
        selection, details = provider.summary_label()
        rendered = prompts.combined_lines(provider)
        self.assertIn(selection, rendered[0].plain)
        self.assertIn(details, rendered[1].plain)
        self.assertIn("perfil " + provider.profile_label, prompts.provider_hint(provider).plain)
        self.assertEqual(provider.profile_name, "Default")
        provider.profile_id, provider.profile_name = "custom", "Default"
        self.assertIn("perfil Default", prompts.provider_hint(provider).plain)
        self.assertEqual(provider.snapshot(), before)

    def test_grouped_combined_hint_does_not_split_translated_labels(self):
        provider = CombinedProvider([GameProvider(), MovieProvider()])
        provider.restore({"selected": ["games", "movies"]})
        i18n.use("qps")
        hint = prompts.provider_hint(provider).plain
        self.assertIn(i18n.t("Games"), hint)
        self.assertEqual(hint.count("⟦"), hint.count("⟧"))

    def test_sort_editor_translates_display_and_saves_order_code(self):
        provider = MovieProvider()
        i18n.use("pt-BR")
        visits = []

        def choose(items, **kwargs):
            index = next(i for i, item in enumerate(items) if item.value == "sort")
            visits.append(items[index].label)
            if len(visits) == 1:
                return index
            self.assertIn(sort_label("newest"), items[index].label)
            return next(i for i, item in enumerate(items) if item.value == "confirm")

        with patch.object(prompts, "arrow_select", side_effect=choose), \
             patch("torrent_finder.ui.result_filters.choose_result_sort", return_value="newest"):
            prompts.filter_menu(provider, on_save=lambda: None)
        self.assertEqual(provider.result_sort, "newest")

    def test_subtitle_summary_localizes_identity_without_changing_choice(self):
        choice = {"mode": "auto", "path": None}
        i18n.use("pt-BR")
        captured = []
        with patch.object(prompts, "arrow_select", side_effect=lambda items, **kw: captured.extend(items)), \
             patch.object(prompts, "has_webtorrent", return_value=True), \
             patch.object(prompts, "has_peerflix", return_value=True), \
             patch.object(prompts, "has_aria2", return_value=True):
            prompts.download_method_prompt(sub_choice=choice)
        self.assertEqual(next(i.label for i in captured if i.value == "set_subs"), "Legendas: detectar no torrent")
        self.assertIn("legendas auto", prompts.torrent_summary(None, subtitles="auto-detect from torrent").plain)
        self.assertIn("legendas não", prompts.torrent_summary(None, subtitles="disabled").plain)
        self.assertEqual(choice, {"mode": "auto", "path": None})

    def test_credential_count_uses_identity_status(self):
        specs = [SimpleNamespace(status=Mock(return_value=status), status_label=Mock(side_effect=AssertionError))
                 for status in ("not set", "saved", "set via environment")]
        i18n.use("pt-BR")
        with patch("torrent_finder.credential_registry.CREDENTIAL_REGISTRY", specs):
            self.assertEqual(prompts._credentials_hint(), "2 de 3 configurados")
        self.assertTrue(all(spec.status.call_count == 1 for spec in specs))

    def test_download_and_batch_client_labels_keep_action_values(self):
        i18n.use("pt-BR")
        captured = []
        with patch.object(prompts, "arrow_select", side_effect=lambda items, **kw: captured.append(items)), \
             patch.object(prompts, "detect_torrent_client", return_value="default torrent client"), \
             patch("torrent_finder.downloader.detect_torrent_client", return_value="default torrent client"), \
             patch.object(prompts, "has_aria2", return_value=True), \
             patch.object(prompts, "has_webtorrent", return_value=True), \
             patch.object(prompts, "has_peerflix", return_value=True), \
             patch("torrent_finder.qbittorrent.configured", return_value=False):
            prompts.download_method_prompt(show_subtitles=False, show_streaming=False)
            prompts.batch_download_menu(2, 2)
        self.assertEqual(next(i.label for i in captured[0] if i.value == "t"), "Abrir em cliente de torrent padrão")
        self.assertEqual(next(i.label for i in captured[1] if i.value == "open"), "Abrir seleção (2) em cliente de torrent padrão")

    def test_torrent_info_translates_generated_text_preserving_site_data(self):
        info = TorrentInfo(source="YTS", title="Back", description="IMDb rating: 8/10\n\nEnglish site text",
                           embedded_subs="yes — 1 embedded track(s): Portuguese (ffprobe)",
                           category="English category", files=[("English.mkv", "1 GB")])
        i18n.use("pt-BR")
        captured = []
        with patch("torrent_finder.torrent_info.fetch_torrent_info", return_value=(info, "")), \
             patch.object(prompts, "arrow_select", side_effect=lambda items, **kw: captured.extend(items)):
            prompts.torrent_info_screen({"source": "YTS"})
        text = "\n".join(item.label for item in captured)
        self.assertIn("Título: Back", text)
        self.assertIn("English category", text)
        self.assertIn(info_label(info.embedded_subs), text)
        self.assertIn(description_label(info.description).splitlines()[0], text)
        self.assertIn("English site text", text)
        self.assertIn("English.mkv", text)
        self.assertEqual(info.title, "Back")

    def test_menu_bar_compacts_when_portuguese_wraps_at_same_width(self):
        screen = Console(file=io.StringIO(), width=80, height=36)
        footers = []
        for language in ("en", "pt-BR"):
            i18n.use(language)
            with patch.object(prompts, "console", screen), \
                 patch.object(prompts, "arrow_select", side_effect=lambda items, **kw: footers.append(kw["footer"]())):
                prompts.search_again_prompt()
        self.assertNotIn("\n", footers[0])
        self.assertIn("\n", footers[1])
        self.assertIn("R/P/M/Tab/H/S/T/C/Q", footers[1])

    def test_main_menu_measures_the_list_column_beside_the_inspector(self):
        i18n.use("qps")
        screen = Console(file=io.StringIO(), width=200, height=50)
        footers = []
        with patch.object(prompts, "console", screen), \
             patch.object(prompts, "arrow_select", side_effect=lambda items, **kw: footers.append(kw["footer"]())):
            prompts.provider_select_prompt()
        self.assertIn("\n", footers[0])
        self.assertIn("Tab", footers[0])

    def test_provider_group_facets_and_notes_use_translated_metadata(self):
        i18n.use("pt-BR")
        seen = []
        with patch.object(prompts, "arrow_select", side_effect=lambda items, **kw: seen.append((items, kw))):
            prompts._provider_group_menu(SOFTWARE_GROUP)
            prompts._provider_source_menu(MovieProvider())
        self.assertEqual(seen[0][1]["title"], SOFTWARE_GROUP.label)
        for row in seen[0][0][:-1]:
            self.assertEqual(row.description, i18n.t(row.value.search_note))
        facets = [row for row in seen[1][0] if isinstance(row.value, tuple) and row.value[0] == "facet"]
        self.assertTrue(facets)
        for row in facets:
            facet = row.value[1]
            self.assertEqual(row.label, "Por " + i18n.t(facet.label).lower())
            self.assertEqual(row.description, i18n.t(facet.note))

    def test_index_room_translates_flavour_and_keeps_saved_query(self):
        i18n.use("pt-BR")
        theme.apply("citrinitas")
        screen = Console(file=io.StringIO(), width=137, height=36)
        rooms = []
        history = [{"provider": "movies", "query": "Back", "timestamp": "2026-10-13T00:00:00"}]
        with patch.object(prompts, "console", screen), \
             patch("torrent_finder.state.load_history", return_value=history), \
             patch.object(prompts, "arrow_select", side_effect=lambda items, **kw: rooms.append(kw["intro"]())):
            prompts.provider_select_prompt()
        heading, words, paths = rooms[0]
        self.assertEqual(heading.plain, "~ O Índice ~")
        self.assertIn("lampião", words.plain)
        self.assertTrue(paths.plain.startswith("Saídas óbvias: "))
        self.assertIn("continuar (Back)", paths.plain)


if __name__ == "__main__":
    unittest.main()
