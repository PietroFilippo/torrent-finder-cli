"""--help and argument errors speak the interface language, chosen before the parser is built."""

import argparse
import contextlib
import io
import unittest
from unittest.mock import patch

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from isolation import isolate_store
from torrent_finder import i18n, main, state


class CommandLineLanguageTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)
        self.addCleanup(setattr, argparse, "_", argparse._)
        main._speak_argparse()

    def help_text(self):
        return main._build_parser().format_help()

    def test_lang_on_the_command_line_is_chosen_before_the_parser(self):
        main._early_language(["--lang", "pt-BR", "--help"])
        self.assertEqual(i18n.current(), "pt-BR")
        text = self.help_text()
        self.assertIn("uso:", text)
        self.assertIn("opções:", text)
        self.assertIn("Busque e baixe torrents.", text)
        self.assertIn("mostra esta ajuda e sai", text)

    def test_a_saved_language_speaks_too(self):
        state.save_setting(i18n.SETTING, "pt-BR")
        main._early_language([])
        self.assertIn("Busque e baixe torrents.", self.help_text())

    def test_english_help_is_unchanged(self):
        main._early_language(["--lang", "en"])
        text = self.help_text()
        self.assertIn("usage:", text)
        self.assertIn("show this help message and exit", text)
        self.assertIn("Search and download torrents.", text)

    def test_argument_errors_are_translated(self):
        main._early_language(["--lang", "pt-BR"])
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), self.assertRaises(SystemExit):
            main._build_parser().parse_args(["-t", "nowhere"])
        self.assertIn("erro: argumento -t/--type: opção inválida", errors.getvalue())

    def test_a_bad_lang_is_left_for_the_parser_to_report(self):
        main._early_language(["--lang", "klingon"])
        self.assertEqual(i18n.current(), "en")
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), self.assertRaises(SystemExit):
            main._build_parser().parse_args(["--lang", "klingon"])
        self.assertIn("klingon", errors.getvalue())

    def test_the_argparse_hook_is_installed_once(self):
        hook = argparse._
        main._speak_argparse()
        self.assertIs(argparse._, hook)

    def test_the_update_preview_reads_no_settings(self):
        with patch("torrent_finder.state.load_setting", side_effect=AssertionError("read settings")):
            main._early_language(["--preview-update"])


if __name__ == "__main__":
    unittest.main()
