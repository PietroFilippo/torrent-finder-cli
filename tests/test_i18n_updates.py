"""Portuguese display text must not change installer, site or saved-result identities."""

import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from rich.console import Console

import isolation  # noqa: F401 — redirects persistence before app modules load
from torrent_finder import fdroid, i18n, knaben, madokami, nyaa, online_fix, rutracker, state, updates
from torrent_finder.providers.madokami_provider import MadokamiProvider
from torrent_finder.providers.rutracker_provider import RuTrackerProvider
from torrent_finder.search_diagnostics import RequestTrace
from torrent_finder.search_session import SearchSession
from torrent_finder.ui import bookmarks, history, inspector, prompts, update_progress
from torrent_finder.utils import relative_time


def render(view, *, width=72, notice=""):
    output = io.StringIO()
    Console(file=output, width=width).print(update_progress.update_panel(view, 3, width, notice))
    return output.getvalue()


class RelativeTimeTests(unittest.TestCase):
    def test_unit_boundaries_and_plural_forms_in_both_languages(self):
        now = datetime(2026, 10, 13, tzinfo=timezone.utc)
        for seconds, english, portuguese in (
            (-60, "just now", "agora mesmo"), (0, "just now", "agora mesmo"),
            (59, "just now", "agora mesmo"), (60, "1m ago", "há 1 min"),
            (300, "5m ago", "há 5 min"), (3599, "59m ago", "há 59 min"),
            (3600, "1h ago", "há 1 h"), (7200, "2h ago", "há 2 h"),
            (86399, "23h ago", "há 23 h"), (86400, "1d ago", "há 1 dia"),
            (3 * 86400, "3d ago", "há 3 dias"), (29 * 86400, "29d ago", "há 29 dias"),
            (30 * 86400, "1mo ago", "há 1 mês"), (120 * 86400, "4mo ago", "há 4 meses"),
        ):
            for language, expected in (("en", english), ("pt-BR", portuguese)):
                with self.subTest(seconds=seconds, language=language):
                    i18n.use(language)
                    self.assertEqual(relative_time((now - timedelta(seconds=seconds)).isoformat(), now), expected)

    def test_invalid_and_timezone_less_times_still_return_empty(self):
        i18n.use("pt-BR")
        for timestamp in (None, 42, "", "bad", "2026-10-13T12:00:00"):
            with self.subTest(timestamp=timestamp):
                self.assertEqual(relative_time(timestamp), "")

    def test_display_callers_accept_portuguese_without_parsing_it(self):
        i18n.use("pt-BR")
        timestamp = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        entry = {"timestamp": timestamp, "provider": "movies", "query": "Dune"}
        self.assertEqual(bookmarks._when(timestamp), "há 5 min")
        self.assertEqual(history._relative_time(timestamp), "há 5 min")
        self.assertEqual(inspector._when(entry), "há 5 min")
        self.assertIn("há 5 min", prompts._continue_item(entry).hint)
        with patch.object(state, "_saved_history", return_value=[entry]):
            self.assertIn("há 5 min", state.history_notes("movies")["Dune"])


class UpdateTranslationTests(unittest.TestCase):
    def setUp(self):
        i18n.use("pt-BR")

    def test_status_label_counts_and_versions(self):
        self.assertEqual(updates.status_label(None), "")
        self.assertEqual(updates.status_label({"kind": "git", "behind": 1}), "1 commit pendente")
        self.assertEqual(updates.status_label({"kind": "git", "behind": 3}), "3 commits pendentes")
        self.assertEqual(updates.status_label({"kind": "pip", "latest": "0.9.1"}), "atualização 0.9.1 pronta")
        self.assertIn("git pull", updates.notice_line({"kind": "git", "behind": 2}))

    def test_installer_english_protocol_yields_translated_details(self):
        calls = []
        output = updates._InstallerOutput(lambda stage, detail="", **extra: calls.append((stage, detail, extra)))
        for line in (
            "Downloading torrent_finder_cli-0.9.1-py3-none-any.whl (719 kB)",
            "Progress 262144 of 719511", "Installing collected packages: torrent-finder-cli",
            "Successfully installed torrent-finder-cli-0.9.1", "ERROR: raw installer error",
        ):
            output.feed(line)
        self.assertEqual(calls[1], ("downloading", "torrent_finder_cli-0.9.1-py3-none-any.whl",
                                   {"done": 262144, "total": 719511}))
        self.assertEqual(calls[2], ("installing", "Instalando torrent-finder-cli.", {}))
        self.assertEqual(calls[3], ("installing", "Instalado: torrent-finder-cli 0.9.1.", {"latest": "0.9.1"}))
        self.assertEqual(output.error, "raw installer error")
        self.assertEqual(output.version, "0.9.1")

    def test_pip_and_pipx_current_and_upgraded_markers_stay_english(self):
        for line in (
            "Requirement already satisfied: torrent-finder-cli in /venv (0.9.1)",
            "torrent-finder-cli is already at latest version 0.9.1 (location: /venv)",
        ):
            output = updates._InstallerOutput(Mock())
            output.feed(line)
            self.assertTrue(output.current)
        output = updates._InstallerOutput(Mock())
        output.feed("upgraded package torrent-finder-cli from 0.9.0 to 0.9.1 (location: /venv)")
        self.assertEqual(output.version, "0.9.1")

    def test_git_current_marker_keeps_restart_off(self):
        def stream(command, log, on_line):
            on_line("Already up to date.")
            return 0
        with patch.object(updates, "_stream", side_effect=stream):
            result = updates._update_checkout(io.StringIO(), Path("update.log"), Mock())
        self.assertTrue(result.ok)
        self.assertFalse(result.restart)
        self.assertEqual(result.message, "Esta cópia do código já está atualizada.")

    def test_legacy_report_states_and_archived_content_stay_english(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / "update-status.json"
            log = Path(directory) / "update.log"
            for code, expected in (
                ("succeeded", "Atualização do pacote concluída."),
                ("failed", "raw installer error"),
                ("pending", "O atualizador não informou a conclusão."),
            ):
                with self.subTest(state=code):
                    raw = json.dumps({"state": code, "started_at": 0, "error": "raw installer error"})
                    status.write_text(raw, encoding="utf-8")
                    with patch.object(updates, "_update_files", return_value=(status, log)):
                        message = updates.consume_update_report()
                    self.assertIn(expected, message)
                    self.assertEqual(status.with_name("last-update-status.json").read_text(encoding="utf-8"), raw)

    def test_translated_completion_keeps_stage_codes_and_freezes_clock(self):
        for code, english, portuguese in (
            ("succeeded", "Update complete", "Atualização concluída"),
            ("failed", "Update did not complete", "Atualização não concluída"),
            ("opened", "Release page opened", "Página de releases aberta"),
        ):
            with self.subTest(stage=code):
                display = update_progress.UpdateDisplay(Console(file=io.StringIO(), width=72))
                with patch.object(display.live, "refresh"), patch.object(update_progress.time, "monotonic", return_value=42):
                    display.update(code)
                self.assertEqual(display.view.stage, code)
                self.assertEqual(display.finished_at, 42)
                self.assertIn(portuguese, render(display.view))
                i18n.use("en")
                self.assertIn(english, render(display.view))
                i18n.use("pt-BR")

    def test_default_and_headings_follow_language_at_draw_time(self):
        i18n.use("en")
        view = update_progress.UpdateView()
        self.assertIn("Preparing update", render(view))
        i18n.use("pt-BR")
        text = render(view)
        self.assertIn("Preparando atualização", text)
        self.assertIn("Preparando a atualização.", text)

    def test_preview_translates_all_stages_without_changing_stage_codes(self):
        stages = [(0, "preparing"), (1, "downloading"), (2, "downloading"),
                  (5, "installing"), (6.5, "finishing"), (7, "succeeded")]
        for elapsed, stage in stages:
            with self.subTest(stage=stage):
                view = update_progress.preview_view(elapsed)
                self.assertEqual(view.stage, stage)
                self.assertNotIn("Installing", render(view))
        self.assertEqual(update_progress.preview_view(7, "failure").stage, "failed")

    def test_portuguese_and_qps_preview_fit_and_translate_once(self):
        for language in ("pt-BR", "qps"):
            i18n.use(language)
            for width in (24, 40, 50, 72, 80, 120):
                for elapsed in (0, 1, 2, 5, 6.5, 7):
                    for outcome in ("success", "failure"):
                        with self.subTest(language=language, width=width, elapsed=elapsed, outcome=outcome):
                            view = update_progress.preview_view(elapsed, outcome)
                            text = render(view, width=width)
                            self.assertTrue(all(len(line) <= width for line in text.splitlines()))
                            if language == "qps":
                                self.assertEqual(view.detail.count("⟦"), 1)
                                self.assertNotIn("⟦⟦", text)


class AdapterTranslationTests(unittest.TestCase):
    def setUp(self):
        i18n.use("pt-BR")

    def test_madokami_rejection_keeps_search_session_identity(self):
        for code in (401, 403):
            with self.subTest(http_status=code):
                session = Mock()
                session.get.return_value.status_code = code
                with patch.object(madokami, "_get_session", return_value=session):
                    results = SearchSession([MadokamiProvider()], ["Saki"]).run()
                diagnostic = results.session.diagnostics[0]
                self.assertEqual(diagnostic.status, "rejected_login")
                self.assertIn("recusou o login", diagnostic.message)

    def test_rutracker_error_statuses_are_independent_of_language(self):
        for reason, status in (("blocked", "blocked"), ("captcha", "login_error"),
                               ("rejected", "rejected_login"), ("unreachable", "error"),
                               ("unexpected", "error")):
            with self.subTest(reason=reason):
                error = rutracker._login_error(reason)
                self.assertEqual(error.status, status)
                self.assertNotEqual(str(error), rutracker._LOGIN_ERRORS[reason][0])
                with patch.object(rutracker, "_get_session", side_effect=error):
                    results = SearchSession([RuTrackerProvider()], ["Saki"]).run()
                self.assertEqual(results.session.diagnostics[0].status, status)

    def test_madokami_saved_names_stay_english_with_separate_display_labels(self):
        base = "/Manga/O/ON/ONE_/One%20Piece"
        for path, english, portuguese in (
            (base, "series folder", "pasta da série"),
            (base + "/Volumes", "folder", "pasta"),
            (base + "/v01.cbz", "file", "arquivo"),
        ):
            with self.subTest(path=path):
                self.assertTrue(madokami.display_name(path).endswith(f"[{english}]"))
                self.assertTrue(madokami.localized_display_name(path).endswith(f"[{portuguese}]"))
        with patch.object(madokami, "_get_session", return_value=Mock()), \
             patch.object(madokami, "_search_paths", return_value=[base]):
            row = madokami.search("One Piece")[0]
        self.assertEqual(row.name, "One Piece [series folder]")
        self.assertEqual(row.handle["mdk_path"], base)

    def test_madokami_display_never_translates_path_names_or_download_folders(self):
        path = "/Manga/O/ON/ONE_/One%20Piece/folder/file.cbz"
        i18n.use("en")
        name = madokami.display_name(path)
        folder = madokami.save_folder(path, "downloads")
        for language, kind in (("pt-BR", "arquivo"), ("qps", i18n.pseudo("file"))):
            with self.subTest(language=language):
                i18n.use(language)
                self.assertEqual(madokami.display_name(path), name)
                self.assertEqual(madokami.save_folder(path, "downloads"), folder)
                self.assertEqual(madokami.localized_display_name(path), f"One Piece › folder › file.cbz [{kind}]")

    def test_verification_booleans_do_not_depend_on_translated_messages(self):
        for status, expected in ((200, True), (401, False), (500, None)):
            with patch.object(madokami.requests, "get", return_value=Mock(status_code=status)):
                ok, message = madokami.test_credentials("user", "password")
            self.assertIs(ok, expected)
            self.assertNotIn("successful", message)
        with patch.object(rutracker, "_login", return_value=(None, "blocked")):
            self.assertEqual(rutracker.test_credentials("user", "password"),
                             (None, "A verificação da Cloudflare no RuTracker bloqueou o app — credenciais não testadas"))

    def test_site_english_markers_still_parse_in_portuguese(self):
        self.assertEqual(online_fix._cooldown_seconds("Try search in 10 seconds"), 10)
        self.assertTrue(rutracker._is_challenge(Mock(headers={}, status_code=403, text="Just a moment")))
        response = Mock(text="No results found", status_code=200)
        with patch.object(nyaa, "search_request", return_value=response):
            self.assertEqual(nyaa.search_page("query", "1_2", 2), [])

    def test_malformed_payload_notices_keep_error_status(self):
        for module, args, message in (
            (fdroid, ("app",), "A resposta do F-Droid não contém uma lista de apps."),
            (knaben, ("query", [1000000]), "A resposta da fonte não contém uma lista de resultados."),
        ):
            with self.subTest(source=module.__name__), RequestTrace() as trace, \
                 patch.object(module, "search_request", return_value=Mock(json=lambda: {})):
                self.assertEqual(module.search(*args), [])
                self.assertEqual(trace.failures, [("error", message)])


if __name__ == "__main__":
    unittest.main()
