"""Data screens translate display text without changing persisted identities."""

from copy import deepcopy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import isolation  # noqa: F401
from isolation import isolate_store
from torrent_finder import i18n, launcher_alias, settings_backup, state, stats, store
from torrent_finder.ui import launcher, stats as stats_ui


class DataLanguageTests(unittest.TestCase):
    def setUp(self):
        self.path = isolate_store(self)

    def test_stats_translate_at_render_and_keep_counter_keys_and_queries(self):
        i18n.use("pt-BR")
        stats.record_session_start()
        stats.record_search("movies", "Back", ["HD"])
        stats.record_creator_search("movies", "director", "Back", [])
        stats.record_method_pick("open_magnet")
        stats.record_method_pick("aria")
        stats.record_method_complete("aria")
        store.flush()
        saved = self.path.read_bytes()
        data = stats.get_all_stats()
        self.assertEqual(data["method_picks"], {"open_magnet": 1, "aria": 1})
        self.assertEqual(data["creator_searches_by_facet"], {"director": 1})
        self.assertEqual(data["top_queries"], {"back": 1})
        self.assertEqual(data["top_creators"], {"Back": 1})
        self.assertEqual(stats_ui.METHOD_NAMES["open_magnet"], "Open in client")
        self.assertEqual(stats_ui.FACET_NAMES["director"], "Director")
        rows = stats_ui._build_items(data)
        labels = [item.label for item in rows]
        for label in ("Abrir no cliente", "Diretor", "back", "Back"):
            self.assertIn(label, labels)
        aria = next(row for row in rows if row.label == "Download via aria2c")
        self.assertIn("1 concluído · 100%", aria.hint.plain)
        i18n.use("en")
        self.assertIn("Open in client", [item.label for item in stats_ui._build_items(data)])
        self.assertEqual(self.path.read_bytes(), saved)

    def test_display_counts_have_singular_plural_and_zero_forms(self):
        i18n.use("pt-BR")
        for count, text in ((0, "0 sessões"), (1, "1 sessão"), (2, "2 sessões")):
            with self.subTest(count=count):
                self.assertIn(text, stats_ui.header_status({"session_count": count}))
                data = {"method_completed": {"aria": count}}
                note = stats_ui._method_items(data)[1].hint.plain
                self.assertIn(f"{count} concluído" + ("" if count == 1 else "s"), note)

    def test_backup_preview_changes_language_but_candidate_and_export_do_not(self):
        payload = {
            "providers": {"movies": {"engine_modes": {"Apibay": "auto"}, "active_presets": ["HD"]}},
            "settings": {"download_dir": "Back", "language": "en", "search_profiles": {
                "version": 1, "active": "default", "profiles": [
                    {"id": "default", "name": "Default", "settings": {"selected": ["movies"]}},
                    {"id": "history", "name": "History search", "settings": {"selected": ["anime"]}},
                ]}},
            "history": [{"query": "Back", "provider": "movies", "timestamp": "2026-10-03T12:00:00+00:00"}],
        }
        original = deepcopy(payload)
        for mode in ("merge", "replace"):
            with self.subTest(mode=mode), patch.object(settings_backup, "uuid4") as uuid:
                uuid.return_value.hex = "stable-id"
                i18n.use("en")
                english, lines_en = settings_backup.prepare_import(payload, mode)
                i18n.use("pt-BR")
                portuguese, lines_pt = settings_backup.prepare_import(payload, mode)
                self.assertEqual(english, portuguese)
                self.assertNotEqual(lines_en, lines_pt)
                self.assertIn("Pasta de downloads: Back (confira se existe neste computador)", lines_pt)
                self.assertTrue(any("1 entrada" in line for line in lines_pt))
        self.assertEqual(payload, original)
        self.assertFalse(self.path.exists())  # previews never write
        store.commit(settings_backup.import_change(payload, "replace"))
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual([entry["name"] for entry in saved["settings"]["search_profiles"]["profiles"]],
                         ["Default", "History search"])
        self.assertEqual(saved["providers"], payload["providers"])
        target = self.path.with_name("backup.json")
        settings_backup.export_settings(target, history=True)
        expected = deepcopy(payload)
        expected["settings"]["combined_search"] = {"selected": ["movies"]}
        self.assertEqual(settings_backup.read_backup(target), expected)

    def test_legacy_backup_keeps_default_profile_identity(self):
        i18n.use("pt-BR")
        candidate, _ = settings_backup.prepare_import({"settings": {"combined_search": {"selected": ["movies"]}}})
        library = candidate["settings"]["search_profiles"]
        self.assertEqual(library["active"], "default")
        self.assertEqual(library["profiles"][0]["name"], "Default")

    def test_state_history_hints_translate_without_rewriting_history(self):
        i18n.use("pt-BR")
        state.add_history_entry("Back", "anime", ["HD"], queries=["Back", "Voltar"])
        state.commit_setting("terminal_command", {"name": "torrent", "path": "Back", "managed": False})
        saved = self.path.read_bytes()
        self.assertIn("2 nomes", state.history_notes("anime")["Back"])
        self.assertEqual(state.load_history()[0]["presets"], ["HD"])
        self.assertEqual(state.load_setting("terminal_command")["name"], "torrent")
        i18n.use("en")
        self.assertIn("2 names", state.history_notes("anime")["Back"])
        self.assertEqual(self.path.read_bytes(), saved)

    def test_unreadable_reason_remains_identity_and_translates_when_displayed(self):
        self.path.write_text("broken", encoding="utf-8")
        problem = store.problem()
        self.assertEqual(problem.reason, "the file is not valid settings data")
        i18n.use("pt-BR")
        self.assertEqual(problem.reason_label(), "o arquivo não contém configurações válidas")
        self.assertIn("Não foi possível ler as configurações salvas", problem.message())
        with self.assertRaisesRegex(ValueError, "Não foi possível ler"):
            store.commit({"settings": {}})
        self.assertEqual(problem.reason, "the file is not valid settings data")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "broken")
        i18n.use("en")
        self.assertIn("Saved settings could not be read", problem.message())
        external = store.StorageProblem("path", "Back", False)
        i18n.use("pt-BR")
        self.assertEqual(external.reason_label(), "Back")

    def test_backup_validation_errors_translate(self):
        i18n.use("pt-BR")
        for data, message in (({"settings": {"language": "invalid"}}, "Idioma da interface inválido"),
                              ({"providers": {"movies": {"engine_modes": {"Apibay": "Sempre"}}}},
                               "Configurações de mecanismos inválidas")):
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, message):
                settings_backup.validate_payload(data)

    def test_launcher_translates_descriptions_but_never_commands_or_shell_text(self):
        target = launcher_alias.LaunchTarget(("python", "-m", "torrent_finder"), "Back")
        english = {platform: launcher_alias._render_launcher(target, platform) for platform in ("win32", "linux")}
        i18n.use("pt-BR")
        for platform, text in english.items():
            self.assertEqual(launcher_alias._render_launcher(target, platform), text)
        rows = launcher._command_items("tf", True)
        self.assertEqual([row.value for row in rows], [*launcher_alias.COMMAND_CHOICES, "back"])
        current = next(row for row in rows if row.value == "tf")
        self.assertEqual(current.hint, "atual")
        self.assertEqual(current.description, "Comando de inicialização mais curto.")
        with tempfile.TemporaryDirectory() as directory, patch.object(launcher_alias, "_find_command", return_value=None):
            status = launcher_alias.set_terminal_command("tf", directory=directory, target=target, platform="win32")
            saved = state.load_setting("terminal_command")
            self.assertEqual(saved["name"], "tf")
            self.assertEqual(saved["path"], status.path)
            self.assertEqual(Path(status.path).read_bytes().decode("utf-8"), english["win32"])


if __name__ == "__main__":
    unittest.main()
