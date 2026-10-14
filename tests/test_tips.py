import unittest
from unittest.mock import patch

from rich.markup import escape

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from torrent_finder import i18n
from torrent_finder.providers import provider_cli_choices
from torrent_finder.ui import tips
from torrent_finder.ui.tips import find_tips


class TipsCatalogTests(unittest.TestCase):
    def test_knaben_fallback_help_is_searchable(self):
        matches = find_tips("Knaben", category="Filters & Selection")
        texts = [tip.text for _category, tip in matches]

        self.assertTrue(any("Set it to Auto" in text for text in texts))
        self.assertTrue(any("Knaben tracker" in text for text in texts))

    def test_engine_mode_semantics_are_searchable(self):
        matches = find_tips("Off engines")

        self.assertTrue(matches)
        self.assertTrue(any(
            "Auto runs after" in tip.text and "unless an active preset" in tip.text
            for _category, tip in matches
        ))


class TipsLanguageTests(unittest.TestCase):
    def test_category_filters_keep_english_identities_in_portuguese(self):
        categories = (
            ("Search & Navigation", "Busca e navegação"),
            ("Search by Creator", "Busca por criador"),
            ("Filters & Selection", "Filtros e seleção"),
            ("Downloads", "Downloads"),
            ("Streaming", "Streaming"),
            ("Subtitles", "Legendas"),
            ("Safety & Privacy", "Segurança e privacidade"),
            ("State & Stats", "Dados e estatísticas"),
            ("Install & Updates", "Instalação e atualizações"),
        )
        i18n.use("pt-BR")
        self.assertEqual(tuple(c.name for c in tips.TIP_CATEGORIES), tuple(name for name, _ in categories))
        for category, (identity, label) in zip(tips.TIP_CATEGORIES, categories):
            with self.subTest(category=identity):
                self.assertEqual(category.name, identity)
                self.assertEqual(i18n.t(category.name), label)
                self.assertEqual(category.display_name(), label)
                self.assertEqual(find_tips(category=identity), [(category, tip) for tip in category.tips])

    def test_display_switches_language_without_changing_text_tags_or_flat_pool(self):
        pool = list(tips.TIPS)
        records = [(tip, tip.text, tip.tags) for tip in tips.iter_tips()]
        for language in ("pt-BR", "qps", "en"):
            i18n.use(language)
            for tip, text, tags in records:
                with self.subTest(language=language, tip=text):
                    self.assertEqual(tip.text, text)
                    self.assertEqual(tip.tags, tags)
                    if language == "en":
                        self.assertEqual(tip.display_text(), text)
                    elif language == "qps":
                        # Key-led prose ("A warning…") follows qps's key-bar
                        # exception and is padded without enclosing brackets.
                        self.assertNotEqual(tip.display_text(), text)
                        self.assertIn("~", tip.display_text())
                    else:
                        self.assertNotEqual(tip.display_text(), text)
            self.assertEqual(tips.TIPS, pool)

    def test_search_matches_both_languages_and_english_tags(self):
        i18n.use("pt-BR")
        english = find_tips("complete release name")
        self.assertTrue(english)
        self.assertEqual(find_tips("NOME COMPLETO DA RELEASE"), english)
        self.assertEqual(find_tips("seguranca e privacidade"), find_tips("Safety & Privacy"))
        subtitle_category = next(c for c in tips.TIP_CATEGORIES if c.name == "Subtitles")
        self.assertEqual(find_tips("legendas", category="Subtitles"),
                         [(subtitle_category, tip) for tip in subtitle_category.tips])
        self.assertTrue(find_tips("multi-title", category="Search & Navigation"))
        i18n.use("en")
        self.assertFalse(find_tips("nome completo da release"))
        self.assertEqual(find_tips("complete release name"), english)

    def test_cli_tip_formats_current_provider_names_after_translation(self):
        tip = next(tip for tip in tips.iter_tips() if tip.text.startswith("Use -t with a provider name"))
        names = ", ".join(provider_cli_choices())
        english = f"Use -t with a provider name for direct CLI searches. Accepted names: {names}."
        self.assertEqual(tip.text, english)
        i18n.use("pt-BR")
        self.assertEqual(tip.display_text(),
                         f"Use -t com o nome de uma categoria para buscar diretamente pela linha de comando. Nomes aceitos: {names}.")
        self.assertEqual(tip.text, english)
        self.assertIn((tips.TIP_CATEGORIES[0], tip), find_tips(names))

    def test_random_footer_translates_at_draw_time_and_escapes_tip_text(self):
        tip = next(tip for tip in tips.iter_tips() if tip.text.startswith("In results, i expands"))
        with patch.object(tips.random, "choice", return_value=tip):
            self.assertEqual(tips.random_tip(), f"[accent]Tip[/accent]  {escape(tip.text)}")
            i18n.use("pt-BR")
            footer = tips.random_tip()
            self.assertTrue(footer.startswith("[accent]Dica[/accent]  Nos resultados"))
            with patch.object(tips.Tip, "display_text", return_value="[warn]tip text[/warn]"):
                self.assertEqual(tips.random_tip(), r"[accent]Dica[/accent]  \[warn]tip text\[/warn]")
            i18n.use("en")
            self.assertEqual(tips.random_tip(), f"[accent]Tip[/accent]  {escape(tip.text)}")


if __name__ == "__main__":
    unittest.main()
