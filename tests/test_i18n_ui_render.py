"""Rendering translations keep stored identities and fit expanded terminal text."""

import datetime as dt
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import isolation  # noqa: F401 — redirects state before importing the UI
from isolation import isolate_store
from rich.cells import cell_len
from rich.console import Console

from torrent_finder import i18n
from torrent_finder.filters import FilterConfig, FilterPreset
from torrent_finder.providers.base import SearchEngine
from torrent_finder.providers.combined_provider import EngineProgress, ProviderProgress, SearchProgress
from torrent_finder.ui import chrome, inspector, search_progress, selector, theme


class RenderLanguageTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)
        i18n.use("pt-BR")

    def test_badges_translate_each_kind_without_changing_state_or_colour(self):
        engine = selector.SelectItem("Nyaa", toggle_states=("On", "Auto", "Off"))
        preset = selector.SelectItem("1080p", toggle_states=("Off", "Require", "Prefer"))
        for item, words in ((engine, ("Sempre", "Auto", "Nunca")), (preset, ("Não", "Exigir", "Preferir"))):
            identities = item.toggle_states
            expected_width = max(map(cell_len, words))
            self.assertEqual(selector._badge_width([item]), expected_width)
            for identity, word in zip(identities, words):
                item.toggle_state = identity
                self.assertEqual(selector._toggle_badge(item), word)
                row = selector._row(item, 0, True, True, selector._geometry([item], True), 0)
                self.assertIn(word, row.plain)
                self.assertTrue(any(row.plain[span.start:span.end] == word and span.style == theme.state_style(identity)
                                    for span in row.spans))
                item.cycle_toggle()
                self.assertEqual(item.toggle_state, identities[(identities.index(identity) + 1) % len(identities)])
            self.assertEqual(item.toggle_states, identities)
        engine.toggle_state = "On"
        i18n.use("qps")
        self.assertIn("⟦", selector._toggle_badge(engine))
        self.assertEqual(engine.toggle_state, "On")
        i18n.use("en")
        self.assertEqual(selector._toggle_badge(engine), "On")

    def test_unicode_actions_labels_and_english_footer_contract(self):
        for footer in ("Enter edit • Esc back", "Enter éditer • Esc voltar", "↑/↓ ações • Ctrl+F filtrar"):
            parsed = theme.parse_footer(footer)
            self.assertEqual([line.plain for line in parsed.keys], footer.split(" • "))
            self.assertEqual(parsed.context, [])
        labelled = theme.labelled("Época: agora · Configurações: padrão")
        labels = [labelled.plain[span.start:span.end] for span in labelled.spans if span.style == theme.MUTED]
        self.assertIn("Época:", labels)
        self.assertIn("Configurações:", labels)
        self.assertEqual(theme.labelled("lowercase: unchanged").spans, [])

    def test_status_date_uses_interface_language_without_locale_formats(self):
        theme.apply("citrinitas")
        with patch("torrent_finder.security.exposure", return_value="exposed"):
            line = chrome.status_line(200, dt.datetime(2026, 10, 4)).plain
        self.assertIn("Buscas:0  Escolhas:0  Favoritos:0  T:", line)
        self.assertIn("dom 4 out", line)
        self.assertIn("IP visível", line)
        self.assertEqual(cell_len(line), 200)
        for month, word in enumerate(("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"), 1):
            self.assertIn(f" 1 {word}", chrome.status_line(200, dt.datetime(2026, month, 1)).plain)
        chrome.clear_messages()
        self.addCleanup(chrome.clear_messages)
        chrome.announce("primeira")
        chrome.announce("segunda")
        self.assertEqual(chrome.take_message(), "primeira [reverse]--Mais--[/reverse]")

    def test_any_key_translates_template_and_accepts_translated_action(self):
        self.assertEqual(theme.any_key(), "[muted]Pressione [key]qualquer tecla[/key] para continuar…[/muted]")
        self.assertIn("para voltar…", theme.any_key("voltar"))
        i18n.use("en")
        self.assertEqual(theme.any_key(), "[muted]Press [key]any key[/key] to continue…[/muted]")

    def test_inspector_credentials_draw_labels_but_compare_english_status(self):
        specs = [SimpleNamespace(display_name=lambda: "Credencial muito longa", status=lambda: "not set",
                                 status_label=lambda: "não definida"),
                 SimpleNamespace(display_name=lambda: "Chave", status=lambda: "set", status_label=lambda: "definida")]
        with patch("torrent_finder.credential_registry.CREDENTIAL_REGISTRY", specs):
            lines = inspector.credentials()[1:]
        self.assertEqual(lines[0].plain.index("não definida"), lines[1].plain.index("definida"))
        self.assertEqual(lines[0].spans[-1].style, theme.MUTED)
        self.assertEqual(lines[1].spans[-1].style, theme.GOOD)

    def test_inspector_saved_presets_and_engine_modes_remain_english(self):
        preset = FilterPreset("With Subtitles", FilterConfig())
        description = "Manga from public trackers (Nyaa Literature + Apibay Comics)."
        engine = SearchEngine("Nyaa", "", lambda query: [], description=description)
        engine.set_mode("on")
        provider = SimpleNamespace(slug="anime", engines=[engine], active_presets=[preset], preferred_presets=[])
        lines = "\n".join(line.plain for line in inspector.provider(provider))
        self.assertIn("Sempre", lines)
        self.assertIn("Com legendas", lines)
        self.assertIn("Mangás de trackers públicos", lines)
        self.assertEqual((preset.name, engine.mode, engine.description), ("With Subtitles", "on", description))
        entry = {"presets": [preset.name], "queries": ["Back"]}
        with patch.object(inspector, "_recent", return_value=[]):
            lines = "\n".join(line.plain for line in inspector.continue_search(entry))
        self.assertIn("Back", lines)  # user text is never translated by the widget
        self.assertIn("Com legendas", lines)
        self.assertEqual(entry["presets"], ["With Subtitles"])

    def test_combined_inspector_uses_provider_display_helper(self):
        child = SimpleNamespace(slug="games", name="Games")
        target = SimpleNamespace(is_combined=True, children=[child], selected_slugs=["games"], slug="all")
        with patch("torrent_finder.ui.prompts.provider_hint", return_value=""), \
                patch.object(inspector, "_recent", return_value=[]):
            lines = "\n".join(line.plain for line in inspector.provider(target))
        self.assertIn("Jogos", lines)
        self.assertEqual((child.slug, child.name, target.selected_slugs), ("games", "Games", ["games"]))

    def test_long_translated_label_columns_align_per_block(self):
        rows = inspector._pairs([("É uma categoria muito longa", "first"), ("Fonte", "second")])
        self.assertEqual(cell_len(rows[0].plain.split("first")[0]), cell_len(rows[1].plain.split("second")[0]))
        i18n.use("qps")
        with patch.object(inspector, "_recent", return_value=[]):
            rows = inspector.continue_search({"queries": ["first"], "presets": ["second"],
                                              "search_profile": {"selected": [], "shared": {"include_keywords": ["third"]}}})
        starts = [cell_len(row.plain[:row.plain.index(word)]) for row, word in zip(rows, ("first", i18n.t("second"), "third"))]
        self.assertEqual(len(set(starts)), 1)

    def test_keys_screen_translates_only_standard_extras(self):
        with patch.object(selector, "arrow_select") as select:
            selector.show_keys("Back", i18n.t("Enter select"))
        items = select.call_args.args[0]
        self.assertEqual([item.label.plain.strip() for item in items[:-1]],
                         ["Enter      selecionar", "↑/↓        mover", "PgUp/PgDn  paginar", "Home/End   primeiro / último", "Esc        voltar"])
        self.assertEqual(items[-1].label, "Voltar")
        self.assertEqual(select.call_args.kwargs["title"].plain, "Teclas › Back")

    def test_owned_frames_fit_both_languages_and_designs_at_required_sizes(self):
        progress = SearchProgress(1, 3, 2, ("Anime",), (
            ProviderProgress("Anime", "running", 0, (EngineProgress("Nyaa", "searching"),)),
            ProviderProgress("Manga · General", "done", 2, (EngineProgress("Knaben", "results", 2),)),
            ProviderProgress("Books", "failed", 0, (EngineProgress("Libgen", "timeout"),))))
        for language in ("pt-BR", "qps"):
            i18n.use(language)
            for design in ("quiet", "citrinitas"):
                theme.apply(design)
                for width, height in ((40, 12), (80, 24), (137, 36), (200, 50)):
                    with self.subTest(language=language, design=design, width=width, height=height):
                        screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
                        items = [selector.SelectItem(str(i), toggle_states=("Off", "Require", "Prefer")) for i in range(80)]
                        with patch.object(selector, "console", screen):
                            frame = selector._build_panel(items, 20, i18n.t("Select"), True, help_key=True)
                        screen.print(frame)
                        lines = screen.file.getvalue().rstrip("\n").splitlines()
                        self.assertLessEqual(len(lines), height)
                        self.assertTrue(all(cell_len(line) <= width for line in lines))
                        self.assertRegex("\n".join(lines), r"\d+–\d+")
                        if width >= 80:
                            self.assertRegex("\n".join(lines), r"\d+–\d+ (?:de|of) 80")
                        screen.file = io.StringIO()
                        with patch.object(search_progress, "console", screen):
                            screen.print(search_progress.progress_frame(i18n.t("Select"), "", [], progress, 2, ""))
                        lines = screen.file.getvalue().rstrip("\n").splitlines()
                        self.assertLessEqual(len(lines), height)
                        self.assertTrue(all(cell_len(line) <= width for line in lines))


if __name__ == "__main__":
    unittest.main()
