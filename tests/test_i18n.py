"""Interface languages (ADR-0028): lookup, plurals, the pseudo-locale, startup resolution and the catalogue checks."""

import contextlib
import ctypes
import io
import json
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirects saved settings before anything reads them
from isolation import isolate_store

from scripts import i18n as tool
from torrent_finder import i18n
from torrent_finder.ui import theme


class CatalogueCase(unittest.TestCase):
    """Points the app at a temporary locales folder; *files* maps "code/name.json" to entries."""

    files: dict = {}

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.locales = Path(directory.name)
        self.write(self.files)
        patcher = patch.object(i18n, "LOCALES", self.locales)
        patcher.start()
        self.addCleanup(patcher.stop)
        i18n.reload()
        self.addCleanup(i18n.reload)

    def write(self, files: dict) -> None:
        for name, entries in files.items():
            path = self.locales / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(entries if isinstance(entries, str) else json.dumps(entries, ensure_ascii=False),
                            encoding="utf-8")


class LookupTests(CatalogueCase):
    files = {
        "pt-BR/common.json": {"Back": "Voltar", "engine mode::Off": "Nunca", "preset state::Off": "Não",
                              "Saved {name}": "{name} salvo", "Broken {name}": "Quebrado {nome}",
                              "{n} result": {"one": "{n} resultado", "other": "{n} resultados"},
                              "{n} match": {"one": "uma correspondência", "other": "{n} correspondências",
                                            "zero": "Nenhuma correspondência"},
                              "{n} time": "{n} vez(es)"},
        "pt-BR/screens.json": {"Settings": "Configurações", "Empty": "", "Bad shape": ["no"]},
        "pt-BR/broken.json": "{not json",
    }

    def test_english_is_the_source_and_needs_no_catalogue(self):
        self.assertEqual(i18n.t("Back"), "Back")
        self.assertEqual(i18n.t("Saved {name}", name="a.json"), "Saved a.json")
        self.assertEqual(i18n.t("Keep {braces} as written"), "Keep {braces} as written")  # no values: not formatted
        self.assertNotIn("en", i18n._catalogues)

    def test_a_language_reads_every_file_in_its_folder_on_first_use(self):
        i18n.use("pt-BR")
        self.assertNotIn("pt-BR", i18n._catalogues)  # nothing read until something is drawn
        self.assertEqual(i18n.t("Back"), "Voltar")
        self.assertEqual(i18n.t("Settings"), "Configurações")
        self.assertEqual(i18n.t("Saved {name}", name="a.json"), "a.json salvo")
        # Empty, malformed and unreadable entries are skipped: the English shows.
        self.assertEqual(i18n.t("Empty"), "Empty")
        self.assertEqual(i18n.t("Bad shape"), "Bad shape")
        self.assertEqual(i18n.t("Not translated"), "Not translated")

    def test_a_context_tells_identical_english_apart(self):
        i18n.use("pt-BR")
        self.assertEqual(i18n.t("Off", ctx="engine mode"), "Nunca")
        self.assertEqual(i18n.t("Off", ctx="preset state"), "Não")
        self.assertEqual(i18n.t("Off"), "Off")

    def test_marked_text_keeps_its_context_and_its_identity(self):
        marked = i18n.N_("Off", ctx="engine mode")
        self.assertEqual(marked, "Off")
        self.assertEqual({"Off": 1}[marked], 1)
        self.assertEqual(json.dumps([marked]), '["Off"]')
        self.assertIs(i18n.N_("Back"), "Back")
        i18n.use("pt-BR")
        self.assertEqual(i18n.t(marked), "Nunca")
        self.assertIs(type(i18n.t(i18n.N_("Untranslated", ctx="x"))), str)

    def test_switching_language_takes_effect_at_the_next_lookup(self):
        labels = {"back": i18n.N_("Back")}
        i18n.use("pt-BR")
        self.assertEqual(i18n.t(labels["back"]), "Voltar")
        i18n.use("en")
        self.assertEqual(i18n.t(labels["back"]), "Back")

    def test_a_broken_translation_falls_back_to_the_english_and_nothing_raises(self):
        i18n.use("pt-BR")
        self.assertEqual(i18n.t("Broken {name}", name="x"), "Broken x")
        self.assertEqual(i18n.t("Saved {name}", other="x"), "Saved {name}")  # a caller's slip shows, not raises
        self.assertEqual(i18n.t("Odd { brace", value=1), "Odd { brace")

    def test_counted_messages(self):
        self.assertEqual([i18n.tn("{n} result", "{n} results", n) for n in (0, 1, 2)],
                         ["0 results", "1 result", "2 results"])
        i18n.use("pt-BR")
        # Portuguese keeps 0 plural on purpose; a "zero" form replaces it where given.
        self.assertEqual([i18n.tn("{n} result", "{n} results", n) for n in (0, 1, 2)],
                         ["0 resultados", "1 resultado", "2 resultados"])
        self.assertEqual([i18n.tn("{n} match", "{n} matches", n) for n in (0, 1, 5)],
                         ["Nenhuma correspondência", "uma correspondência", "5 correspondências"])
        self.assertEqual(i18n.tn("{n} time", "{n} times", 3), "3 vez(es)")
        self.assertEqual(i18n.tn("{n} result", "{n} results", 1234, n="1,234"), "1,234 resultados")
        self.assertEqual(i18n.tn("{n} unknown", "{n} unknowns", 2), "2 unknowns")
        self.assertEqual(i18n.t("{n} result"), "{n} resultados")  # a plural entry asked for as one message

    def test_languages_and_codes(self):
        self.assertEqual(i18n.languages(), {"en": "English", "pt-BR": "Português (Brasil)"})
        for spelling in ("pt", "pt_BR", "ptbr", "pt-br", "PT-PT.UTF-8", "pt_BR.utf8@euro", "Português"):
            self.assertEqual(i18n.normalise(spelling), "pt-BR", spelling)
        for spelling in ("en", "en_US", "en-GB", "English"):
            self.assertEqual(i18n.normalise(spelling), "en", spelling)
        for spelling in ("C", "POSIX", "auto", "de_DE", "xx", "", None, 3):
            self.assertIsNone(i18n.normalise(spelling), spelling)
        self.assertEqual(i18n.normalise("qps"), "qps")
        self.assertEqual(i18n.use("pt_BR"), "pt-BR")
        self.assertEqual(i18n.current(), "pt-BR")
        self.assertEqual(i18n.use("klingon"), "en")
        with patch.object(i18n, "system_language", lambda environ=None, platform=None: "pt-BR"):
            self.assertEqual(i18n.use("auto"), "pt-BR")


class PseudoLocaleTests(unittest.TestCase):
    def setUp(self):
        i18n.use("qps")

    def test_messages_are_bracketed_accented_and_padded(self):
        shown = i18n.t("Settings › Appearance")
        self.assertTrue(shown.startswith("⟦S") and shown.endswith("~⟧"), shown)
        self.assertIn("Séttíngs › Appéáráncé", shown)
        padding = shown.count("~")
        self.assertTrue(0.3 <= padding / len("Settings › Appearance") <= 0.45, padding)

    def test_protected_tokens_and_separators_stay(self):
        text = ("Use --theme or TORRENT_FINDER_THEME, see filter_state.json and https://example.org/a. "
                "Press Ctrl+C or Esc  •  [warn]{count} left[/warn]\nsecond line")
        shown = i18n.t(text, count=3)
        for token in ("--theme", "TORRENT_FINDER_THEME", "filter_state.json", "https://example.org/a", "Ctrl+C",
                      "Esc", "  •  ", "[warn]", "[/warn]", "3 "):
            self.assertIn(token, shown)
        self.assertEqual(shown.count("\n"), 1)
        from rich.text import Text
        Text.from_markup(shown)  # still valid markup

    def test_counted_messages_and_values_survive(self):
        self.assertIn("2 résúlts", i18n.tn("{n} result", "{n} results", 2))
        self.assertIn("1 résúlt", i18n.tn("{n} result", "{n} results", 1))

    def test_key_bars_still_read_as_the_same_keys(self):
        for bar in ("↑/↓ navigate  •  Enter apply  •  Space preview  •  Esc back", "R reveal",
                    "Tab actions  •  ? keys", "Ctrl+F filters  •  a all  •  i invert", "PgUp/PgDn page  •  Home top"):
            english, pseudo = theme.parse_footer(bar), theme.parse_footer(i18n.t(bar))
            self.assertEqual([segment.plain.split(" ", 1)[0] for segment in pseudo.keys],
                             [segment.plain.split(" ", 1)[0] for segment in english.keys], bar)
            self.assertFalse(pseudo.context, bar)
            self.assertNotEqual(i18n.t(bar), bar)


class ResolutionTests(unittest.TestCase):
    def test_the_command_line_wins_then_the_environment_then_the_saved_choice(self):
        environ = {i18n.ENV: "en"}
        self.assertEqual(i18n.resolve("pt", environ, "en"), ("pt-BR", "cli", ""))
        self.assertEqual(i18n.resolve(None, {i18n.ENV: "pt_BR"}, "en"), ("pt-BR", "env", ""))
        self.assertEqual(i18n.resolve(None, {}, "pt-BR"), ("pt-BR", "saved", ""))
        self.assertEqual(i18n.resolve(None, {}, None), ("en", "system", ""))
        self.assertEqual(i18n.resolve("qps", {}, None)[0], "qps")

    def test_auto_at_any_step_asks_the_system(self):
        with patch.object(i18n, "system_language", lambda environ=None, platform=None: "pt-BR"):
            self.assertEqual(i18n.resolve("auto", {i18n.ENV: "en"}, "en"), ("pt-BR", "cli", ""))
            self.assertEqual(i18n.resolve(None, {i18n.ENV: "AUTO"}, "en"), ("pt-BR", "env", ""))
            self.assertEqual(i18n.resolve(None, {}, "auto"), ("pt-BR", "saved", ""))
            self.assertEqual(i18n.resolve(None, {}, None), ("pt-BR", "system", ""))

    def test_an_unknown_environment_value_is_named_and_skipped(self):
        code, source, notice = i18n.resolve(None, {i18n.ENV: "klingon"}, "pt-BR")
        self.assertEqual((code, source), ("pt-BR", "saved"))
        self.assertEqual(notice, f"Ignoring {i18n.ENV}=klingon: not a language (auto, en, pt-BR).")

    def test_unknown_saved_values_are_ignored_quietly(self):
        for saved in ("klingon", "qps", 3, {"code": "pt"}, ""):
            self.assertEqual(i18n.resolve(None, {}, saved), ("en", "system", ""), saved)

    def test_startup_uses_the_language_and_words_the_notice_in_it(self):
        notice = i18n.apply_startup("pt-BR", {i18n.ENV: "klingon"})
        self.assertEqual(i18n.current(), "pt-BR")
        self.assertEqual(i18n.source(), "cli")
        self.assertEqual(notice, f"Ignorando {i18n.ENV}=klingon: não é um idioma (auto, en, pt-BR).")

    def test_a_portuguese_region_suggests_portuguese_only_when_nothing_chose(self):
        self.assertEqual(i18n.region_suggests("en", "pt-BR"), "pt-BR")
        self.assertEqual(i18n.region_suggests("en", "pt_PT.UTF-8"), "pt-BR")
        self.assertIsNone(i18n.region_suggests("en", "en-US"))
        self.assertIsNone(i18n.region_suggests("en", "de-DE"))
        self.assertIsNone(i18n.region_suggests("pt-BR", "pt-BR"))
        i18n.apply_startup(None, {}, None)
        self.assertEqual(i18n.suggestion("pt-BR"), "pt-BR")
        i18n.apply_startup(None, {}, "en")  # chosen in Settings: no hint
        self.assertIsNone(i18n.suggestion("pt-BR"))
        i18n.apply_startup(None, {i18n.ENV: "en"}, None)
        self.assertIsNone(i18n.suggestion("pt-BR"))
        i18n.apply_startup(None, {}, None)
        self.assertIsNone(i18n.suggestion())  # the suite's system region is English


class _Kernel32:
    """Stands in for kernel32: preferred display languages, the default UI language, the regional format."""

    def __init__(self, preferred: str | None, default_ui: str = "en-US", region: str = "pt-BR"):
        self.preferred, self.default_ui, self.region = preferred, default_ui, region

    def GetUserPreferredUILanguages(self, flags, count, names, size):
        if self.preferred is None:
            return 0
        listed = self.preferred + "\0\0"
        if names is None:
            size._obj.value = len(listed)
        else:
            names[:len(listed)] = listed
        return 1

    def GetUserDefaultUILanguage(self):
        return 0x0409

    def LCIDToLocaleName(self, lcid, name, length, flags):
        name.value = self.default_ui
        return len(self.default_ui) + 1

    def GetUserDefaultLocaleName(self, name, length):
        name.value = self.region
        return len(self.region) + 1


class DetectionTests(unittest.TestCase):
    def test_windows_uses_the_first_display_language_not_the_region(self):
        self.assertEqual(i18n._windows_ui_language(_Kernel32("en-US\0pt-BR")), "en-US")
        self.assertEqual(i18n._windows_ui_language(_Kernel32("pt-BR\0en-US")), "pt-BR")
        self.assertEqual(i18n._windows_ui_language(_Kernel32(None, default_ui="pt-BR")), "pt-BR")
        self.assertEqual(i18n._windows_region(_Kernel32("en-US")), "pt-BR")

    def test_posix_follows_gettext(self):
        language = i18n._posix_language
        self.assertEqual(language({"LANG": "pt_BR.UTF-8"}), "pt_BR.UTF-8")
        self.assertEqual(language({"LANG": "en_US.UTF-8", "LC_MESSAGES": "pt_BR.UTF-8"}), "pt_BR.UTF-8")
        self.assertEqual(language({"LANG": "pt_BR.UTF-8", "LC_ALL": "en_GB.UTF-8"}), "en_GB.UTF-8")
        self.assertEqual(language({"LANGUAGE": "de:pt_BR:en", "LANG": "en_US.UTF-8"}), "pt_BR")
        self.assertEqual(language({"LANGUAGE": "pt_BR", "LANG": "C.UTF-8"}), "en")  # C wins over LANGUAGE
        self.assertIsNone(language({}))
        self.assertEqual(i18n._posix_region({"LANG": "en_US.UTF-8", "LC_TIME": "pt_BR.UTF-8"}), "pt_BR.UTF-8")

    def test_the_system_probes_never_raise(self):
        real = isolation.SYSTEM_PROBES
        with patch.object(i18n, "system_language", real["system_language"]), \
                patch.object(i18n, "system_region", real["system_region"]):
            self.assertEqual(i18n.detect({"LANG": "pt_BR.UTF-8"}, platform="linux"), "pt-BR")
            self.assertEqual(i18n.detect({"LC_ALL": "POSIX"}, platform="linux"), "en")
            self.assertEqual(i18n.detect({}, platform="linux"), "en")
            with patch.object(i18n, "_windows_ui_language", side_effect=OSError("no kernel32")):
                self.assertIsNone(i18n.system_language(platform="win32"))
                self.assertEqual(i18n.detect(platform="win32"), "en")

    @unittest.skipUnless(sys.platform == "win32", "reads this Windows' own languages")
    def test_the_windows_probes_read_this_machine(self):
        for probe in (i18n._windows_ui_language, i18n._windows_region):
            value = probe()
            self.assertTrue(value is None or (isinstance(value, str) and "-" in value), value)
        self.assertIsInstance(ctypes.WinDLL("kernel32").GetUserDefaultUILanguage(), int)


class BaselineTests(unittest.TestCase):
    def test_every_test_runs_in_english(self):
        self.assertEqual(i18n.current(), "en")
        self.assertNotIn(i18n.ENV, os.environ)
        self.assertEqual(i18n.system_language(), "en-US")
        self.assertEqual(i18n.system_region(), "en-US")

    def test_the_baseline_undoes_a_language_and_the_variable(self):
        os.environ[i18n.ENV] = "pt-BR"
        i18n.use("pt-BR")
        isolation.restore_baseline()
        self.assertEqual(i18n.current(), "en")
        self.assertNotIn(i18n.ENV, os.environ)


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)

    def parse(self, *argv):
        from torrent_finder.main import _build_parser
        return _build_parser().parse_args(list(argv))

    def test_lang_takes_any_spelling_and_hides_the_pseudo_locale(self):
        self.assertEqual(self.parse("--lang", "pt").lang, "pt-BR")
        self.assertEqual(self.parse("--lang", "Auto").lang, "auto")
        self.assertEqual(self.parse("--lang", "qps").lang, "qps")
        self.assertIsNone(self.parse().lang)
        from torrent_finder.main import _build_parser
        help_text = _build_parser().format_help()
        self.assertIn("{auto,en,pt-BR}", help_text)
        self.assertNotIn("qps", help_text)
        with self.assertRaises(SystemExit), patch("sys.stderr", io.StringIO()) as error:
            self.parse("--lang", "klingon")
        self.assertIn("choose from auto, en, pt-BR", error.getvalue())

    def test_a_restart_keeps_the_language(self):
        from torrent_finder.main import _restart_args
        self.assertEqual(_restart_args(self.parse("-y", "--lang", "pt", "--theme", "iris")),
                         ["--skip-warning", "--lang", "pt-BR", "--theme", "iris"])
        self.assertEqual(_restart_args(self.parse()), [])

    def test_startup_reads_the_saved_language(self):
        from torrent_finder import main
        from torrent_finder.state import commit_setting
        commit_setting(i18n.SETTING, "pt-BR")
        self.assertEqual(main._apply_language(self.parse()), "")
        self.assertEqual((i18n.current(), i18n.source()), ("pt-BR", "saved"))
        main._apply_language(self.parse("--lang", "en"))
        self.assertEqual((i18n.current(), i18n.source()), ("en", "cli"))

    def test_an_unreadable_store_and_the_update_preview_leave_the_settings_alone(self):
        from torrent_finder import main
        with patch("torrent_finder.state.load_setting", side_effect=ValueError("unreadable")):
            main._apply_language(self.parse())
        self.assertEqual((i18n.current(), i18n.source()), ("en", "system"))
        with patch("torrent_finder.state.load_setting", side_effect=AssertionError("settings were read")):
            main._apply_language(SimpleNamespace(preview_update="success"))

    def test_the_language_is_chosen_before_the_first_frame(self):
        from torrent_finder import main
        with patch.object(main, "preview_update") as preview, patch.object(main, "_apply_appearance", return_value=""):
            main._main_loop(self.parse("--lang", "pt-BR", "--preview-update"))
        preview.assert_called_once()
        self.assertEqual(i18n.current(), "pt-BR")


# --- the checks scripts/i18n.py runs -----------------------------------------------------

GLOSSARY = {
    "terms": [{"term": "search", "use": "buscar", "forbidden": ["pesquis*"]},
              {"term": "file", "use": "arquivo", "forbidden": ["ficheiro"]},
              {"term": "download", "use": "baixar", "forbidden": ["transferênc*"],
               "allowed": ["área de transferência"]},
              {"term": "Off", "ctx": "engine mode", "use": "Nunca"}],
    "keep": ["Athanor"],
}


class ShippedCatalogueTests(unittest.TestCase):
    def test_the_code_and_every_shipped_catalogue_pass_every_check(self):
        problems = tool.check()
        self.assertEqual([], [str(problem) for problem in problems])

    def test_converted_modules_hold_no_bare_ui_text(self):
        self.assertEqual([], [str(problem) for problem in tool.bare_problems(tool.extract())])

    def test_the_seed_catalogue_is_reserved_until_code_uses_it(self):
        catalogue = tool.merged("pt-BR")
        for msgid, ctx in tool.RESERVED:
            self.assertIn(f"{ctx}::{msgid}" if ctx else msgid, catalogue)
        extraction = tool.extract()
        self.assertIn("Ignoring {variable}={value}: not a language ({choices}).", extraction.messages)

    def test_the_commands_run(self):
        for argv, code in ((["stats"], 0), (["check"], 0), (["check", "pt"], 0), (["extract"], 0),
                           (["todo", "pt-BR"], 0)):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(tool.main(argv), code, argv)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            tool.main(["extract", "--json"])
        self.assertEqual(json.loads(output.getvalue())["problems"], [])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            tool.main(["todo", "pt-BR", "--json"])
        self.assertEqual(json.loads(output.getvalue()), [])


class EntryCheckTests(unittest.TestCase):
    def problems(self, english, text, ctx="", budget=None, plural=None):
        message = tool.Message(english, ctx, plural)
        if budget is not None:
            message.sites.append(tool.Site("x.py", 1, 1, "f", "t", budget))
        return [problem.check for problem in tool.entry_problems(message, text, "here", GLOSSARY)]

    def test_a_faithful_translation_passes(self):
        self.assertEqual(self.problems("Press [key]any key[/key] to continue…",
                                       "Pressione [key]qualquer tecla[/key] para continuar…"), [])
        self.assertEqual(self.problems("↑/↓ navigate  •  Enter select  •  Esc back",
                                       "↑/↓ navegar  •  Enter selecionar  •  Esc voltar"), [])
        self.assertEqual(self.problems("{n} result", {"one": "um resultado", "other": "{n} resultados",
                                                      "zero": "Nenhum resultado"}, plural="{n} results"), [])

    def test_each_check_catches_its_problem(self):
        cases = [
            ("placeholders", "Saved {name}", "{nome} salvo"),
            ("placeholders", "Saved {name}", "Salvo"),
            ("markup", "[warn]Careful[/warn] now", "Cuidado agora"),
            ("markup", "[warn]Careful[/warn]", "[warn]Cuidado[/aviso]"),
            ("separators", "Settings › Appearance", "Configurações - Aparência"),
            ("separators", "Enter select  •  Esc back", "Enter selecionar, Esc voltar"),
            ("separators", "One\nTwo", "Um Dois"),
            ("protected", "Use --theme for one run", "Use o tema para uma execução"),
            ("protected", "Saved in filter_state.json", "Salvo no arquivo de estado"),
            ("protected", "Press Ctrl+C to stop", "Pressione Control+C para parar"),
            ("protected", "See https://example.org/help", "Veja a ajuda"),
            ("protected", "Set TORRENT_FINDER_LANG first", "Defina o idioma primeiro"),
            ("protected", "Press F to filter", "Pressione G para filtrar"),
            ("keys", "Enter select  •  Esc back", "Esc voltar  •  Enter selecionar"),
            ("keys", "Enter edit  •  Esc back", "Enter éditer  •  Esc voltar"),
            ("nfc", "Back", "Voltar e\u0301"),
            ("empty", "Back", "  "),
            ("glossary", "Search again", "Pesquisar de novo"),
            ("glossary", "Open the file", "Abrir o ficheiro"),
            ("glossary", "The Athanor design", "O design Atanor"),
            ("shape", "Back", {"one": "Voltar", "other": "Voltar"}),
        ]
        for check, english, text in cases:
            with self.subTest(english=english, text=text):
                self.assertIn(check, self.problems(english, text))

    def test_context_terms_budgets_and_plural_shapes(self):
        self.assertIn("glossary", self.problems("Off", "Desligado", ctx="engine mode"))
        self.assertIn("glossary", self.problems("Download finished", "Transferência concluída"))
        self.assertEqual(self.problems("Copied to the clipboard", "Copiado para a área de transferência"), [])
        self.assertEqual(self.problems("Off", "Nunca", ctx="engine mode"), [])
        self.assertIn("budget", self.problems("Age", "Idade aproximada", budget=5))
        self.assertEqual(self.problems("Age", "Idade", budget=5), [])
        self.assertIn("shape", self.problems("{n} result", "{n} resultado(s)", plural="{n} results"))
        self.assertIn("shape", self.problems("{n} result", {"other": "{n} resultados"}, plural="{n} results"))
        self.assertIn("placeholders", self.problems("{n} result", {"one": "um", "other": "resultados"},
                                                    plural="{n} results"))

    def test_prose_that_starts_with_a_letter_is_not_a_key_bar(self):
        self.assertEqual(self.problems("A raven arrives: version 2 is out. U installs it.",
                                       "Um corvo chega: a versão 2 saiu. U a instala."), [])


class CodeCheckTests(unittest.TestCase):
    def extract(self, source: str):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "module.py"
        path.write_text(source, encoding="utf-8")
        return tool.extract([path], reserved=False), path

    def checks(self, source: str) -> list[str]:
        return [problem.check for problem in self.extract(source)[0].problems]

    def test_messages_are_found_with_their_context_place_and_budget(self):
        extraction, _path = self.extract(
            "from torrent_finder.i18n import t, tn as plural, N_\n"
            "from torrent_finder import i18n as words\n"
            "LABEL = N_('Off', ctx='engine mode')\n"
            "def draw(count, on):\n"
            "    t('Age', ctx='column')  # i18n: budget=5\n"
            "    plural('{n} result', '{n} results', count)\n"
            "    words.t('On' if on else 'Off', ctx='toggle')\n"
            "    t(LABEL)\n")
        messages = extraction.messages
        self.assertEqual(set(messages), {"engine mode::Off", "column::Age", "{n} result", "toggle::On", "toggle::Off"})
        self.assertEqual(messages["column::Age"].budget, 5)
        self.assertEqual(messages["{n} result"].plural, "{n} results")
        self.assertEqual(messages["column::Age"].sites[0].function, "draw")
        self.assertEqual([item.expression for item in extraction.dynamic], ["LABEL"])
        self.assertEqual(extraction.problems, [])

    def test_translating_at_import_time_is_refused(self):
        self.assertEqual(self.checks("from torrent_finder.i18n import t\nTITLE = t('Settings')\n"), ["import-time"])
        self.assertEqual(self.checks("from torrent_finder.i18n import t\nclass A:\n    name = t('Back')\n"),
                         ["import-time"])
        self.assertEqual(self.checks("from torrent_finder.i18n import t\ndef f(label=t('Back')):\n    pass\n"),
                         ["import-time"])
        self.assertEqual(self.checks("from torrent_finder.i18n import t\n"
                                     "def f():\n    class B:\n        name = t('Back')\n    return lambda: t('Back')\n"),
                         [])

    def test_text_the_catalogue_cannot_hold_is_refused(self):
        self.assertEqual(self.checks("from torrent_finder.i18n import t\ndef f(x):\n    t(f'Saved {x}')\n"),
                         ["computed"])
        self.assertEqual(self.checks("from torrent_finder.i18n import t\ndef f(x):\n    t('Saved ' + x)\n"),
                         ["computed"])
        self.assertEqual(self.checks("from torrent_finder.i18n import t\ndef f(x):\n    t('Back', ctx=x)\n"),
                         ["computed"])

    def test_values_must_match_the_placeholders(self):
        self.assertEqual(self.checks("from torrent_finder.i18n import t\ndef f(x):\n    t('Saved {name}', nmae=x)\n"),
                         ["placeholders"])
        self.assertEqual(self.checks("from torrent_finder.i18n import t\ndef f(x):\n    t('Saved {}', name=x)\n"),
                         ["placeholders"])
        self.assertEqual(self.checks("from torrent_finder.i18n import t\ndef f():\n    t('Use {{braces}}')\n"),
                         ["placeholders"])
        self.assertEqual(self.checks("from torrent_finder.i18n import t, N_\nX = N_('Saved {name}')\n"
                                     "def f(v):\n    t('Saved {name}', **v)\n"), [])

    def test_a_local_name_t_is_not_the_translation_function(self):
        extraction, _path = self.extract("import time\ndef f(t):\n    return t('not a message')\n")
        self.assertEqual((extraction.messages, extraction.problems), ({}, []))


class BareLiteralTests(unittest.TestCase):
    def bare(self, source: str) -> list[str]:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "screen.py"
        path.write_text(source, encoding="utf-8")
        return [text for _line, text in tool.bare_literals(path, keep=("Athanor",))]

    def test_ui_text_outside_t_is_found(self):
        found = self.bare(
            '"""A screen."""\n'
            "from torrent_finder.i18n import t, N_\n"
            "HELP = 'Shows the painting behind the app.'\n"
            "MARKED = N_('Marked text is fine.')\n"
            "def draw(name, mode):\n"
            "    '''Draws it.'''\n"
            "    print(t('Converted text'))\n"
            "    print(f'Saved {name} in the folder')\n"
            "    print('Back')\n"
            "    print('Esc back  •  Enter select')\n"
            "    print('Athanor')\n"
            "    print('Kept as English on purpose')  # i18n: ignore\n"
            "    if mode == 'Some Label':\n"
            "        return {'Key Name': 1}.get('Other Key', 'theme')\n"
            "    return name.startswith('Not this'), 'slug-like', 'snake_case', '[bold]{}[/bold]', 'Ctrl+C'\n")
        self.assertEqual(found, ["Shows the painting behind the app.", "Saved {} in the folder", "Back",
                                 "Esc back  •  Enter select"])

    def test_the_converted_mark_puts_a_module_under_the_check(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "screen.py"
        path.write_text("# i18n: converted\ndef draw():\n    print('Left behind')\n", encoding="utf-8")
        extraction = tool.extract([path], reserved=False)
        self.assertEqual(len(extraction.converted), 1)
        with patch.object(tool, "ROOT", Path(directory.name)):
            extraction.converted = ["screen.py"]
            self.assertEqual([problem.check for problem in tool.bare_problems(extraction)], ["bare"])


class CatalogueCheckTests(CatalogueCase):
    files = {
        "pt-BR/a.json": {"Back": "Voltar", "Old": "Velho", "Saved {name}": "{name} salvo"},
        "pt-BR/b.json": {"Back": "Retornar"},
        "pt-BR/c.json": "[1, 2]",
        "de/a.json": {},
    }

    def extraction(self) -> "tool.Extraction":
        extraction = tool.Extraction()
        for msgid in ("Back", "Saved {name}", "Missing one"):
            extraction.add(tool.Message(msgid), tool.Site("torrent_finder/x.py", 3, 3, "draw", "t"))
        return extraction

    def test_missing_obsolete_conflicting_and_unreadable(self):
        checks = sorted(problem.check for problem in tool.catalogue_problems("pt-BR", self.extraction()))
        self.assertEqual(checks, ["conflict", "file", "missing", "obsolete"])

    def test_folders_match_the_shipped_languages(self):
        self.assertEqual([problem.check for problem in tool.layout_problems()], ["layout"])

    def test_todo_lists_what_is_missing_with_its_code_and_glossary(self):
        extraction = self.extraction()
        extraction.messages["Missing one"].sites[0] = tool.Site("torrent_finder/i18n.py", 40, 40, "draw", "t", 12)
        extraction.add(tool.Message("Search again"), tool.Site("torrent_finder/i18n.py", 41, 41, "draw", "t"))
        with patch.object(tool, "extract", return_value=extraction):
            entries = tool.todo("pt-BR")
            self.assertEqual([entry["msgid"] for entry in entries], ["Missing one", "Search again"])
            self.assertEqual(entries[0]["budget"], 12)
            self.assertTrue(any(line.startswith(">") for line in entries[0]["sites"][0]["code"]))
            self.assertEqual(entries[1]["glossary"][0]["use"], "buscar (verb), busca (noun)")
            self.assertEqual(tool.todo("pt-BR", files=["torrent_finder/other.py"]), [])
            with contextlib.redirect_stdout(io.StringIO()) as output:
                tool._print_todo("pt-BR", entries)
            self.assertIn('"Missing one": ""', output.getvalue())


if __name__ == "__main__":
    unittest.main()
