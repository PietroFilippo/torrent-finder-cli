"""Settings › Language: the row, the choice saved and used at once, and the one-time hint."""

import unittest
from unittest.mock import patch

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from isolation import isolate_store
from torrent_finder import i18n, main, state
from torrent_finder.ui import chrome, prompts


def _rows(screen, **kwargs):
    """The rows *screen* offers, leaving it at once."""
    seen = []

    def capture(items, **_kwargs):
        seen.append(list(items))
        return None

    with patch.object(prompts, "arrow_select", side_effect=capture):
        screen(**kwargs)
    return seen[0]


class LanguageSettingTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)
        chrome.clear_messages()
        self.addCleanup(chrome.clear_messages)

    def choose(self, value):
        items = _rows(prompts.language_menu)
        index = [item.value for item in items].index(value)
        with patch.object(prompts, "arrow_select", return_value=index):
            prompts.language_menu()

    def test_settings_lists_the_language_with_what_chose_it(self):
        row = next(item for item in _rows(prompts.settings_menu) if item.value == "__language__")
        self.assertEqual(row.label, "Language")
        self.assertEqual(row.hint, "English (system)")

    def test_the_menu_offers_automatic_and_every_language_in_its_own_words(self):
        items = _rows(prompts.language_menu)
        self.assertEqual([item.value for item in items], [i18n.AUTO, "en", "pt-BR", None])
        self.assertEqual(items[0].label, "Automatic (system: English)")
        self.assertEqual(items[2].label, "Português (Brasil)")
        self.assertEqual(items[2].hint, "menus e mensagens em português")

    def test_a_choice_is_saved_and_used_at_once(self):
        self.choose("pt-BR")
        self.assertEqual(state.load_setting(i18n.SETTING), "pt-BR")
        self.assertEqual(i18n.current(), "pt-BR")
        self.assertEqual(chrome.take_message(), "Idioma: Português (Brasil).")
        row = next(item for item in _rows(prompts.settings_menu) if item.value == "__language__")
        self.assertEqual(row.label, "Idioma · Language")  # found again in either language
        self.assertEqual(row.hint, "Português (Brasil)")

    def test_automatic_is_saved_as_auto_and_follows_the_system(self):
        self.choose("pt-BR")
        self.choose(i18n.AUTO)
        self.assertEqual(state.load_setting(i18n.SETTING), i18n.AUTO)
        self.assertEqual(i18n.current(), "en")
        row = next(item for item in _rows(prompts.settings_menu) if item.value == "__language__")
        self.assertEqual(row.hint, "English (system)")

    def test_a_language_from_the_command_line_says_it_still_wins_at_startup(self):
        i18n.apply_startup("en")
        self.choose("pt-BR")
        chrome.take_message()
        self.assertIn("--lang", chrome.take_message())


class LanguageHintTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)
        chrome.clear_messages()
        self.addCleanup(chrome.clear_messages)

    def test_an_english_windows_in_brazil_is_told_once_in_portuguese(self):
        with patch.object(i18n, "suggestion", return_value="pt-BR"):
            main._offer_language_once()
            self.assertEqual(chrome.take_message(), "Prefere português? Configurações › Idioma")
            main._offer_language_once()
            self.assertEqual(chrome.take_message(), "")

    def test_no_hint_without_a_suggestion(self):
        with patch.object(i18n, "suggestion", return_value=None):
            main._offer_language_once()
        self.assertEqual(chrome.take_message(), "")
        self.assertFalse(state.load_setting(i18n.HINT_SETTING, False))


if __name__ == "__main__":
    unittest.main()
