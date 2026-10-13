"""Credential identities and network privacy survive interface-language changes."""

import io
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, PropertyMock, patch

import isolation  # noqa: F401  # redirect persistence before drawing any screen
import readchar
from rich.console import Console

from torrent_finder import credentials, i18n, qbittorrent, security, terminal_check
from torrent_finder.credential_registry import CREDENTIAL_REGISTRY, get_credential_spec
from torrent_finder.ui import credentials as ui
from torrent_finder.ui import qbittorrent as client_ui


class CredentialsI18nTests(unittest.TestCase):
    def test_status_identity_stays_english_and_display_changes_at_runtime(self):
        spec = get_credential_spec("tmdb")
        cases = ((None, None, "not set", "não definido"),
                 ("fixture-key", "file", "saved", "salvo"),
                 ("fixture-key", "env", "set via environment", "definido por variável de ambiente"))
        for value, source, identity, portuguese in cases:
            with patch.object(credentials, "get_credential", return_value=value), \
                 patch.object(credentials, "credential_source", return_value=source):
                for language in ("pt-BR", "qps", "en"):
                    with self.subTest(status=identity, language=language):
                        i18n.use(language)
                        self.assertEqual(spec.status(), identity)
                        expected = (portuguese if language == "pt-BR" else
                                    i18n.pseudo(identity) if language == "qps" else identity)
                        self.assertEqual(spec.status_label(), expected)

    def test_registry_names_and_fields_keep_their_identity(self):
        spec = get_credential_spec("tmdb")
        field = get_credential_spec("opensubtitles").fields[0]
        for language in ("pt-BR", "qps", "en"):
            with self.subTest(language=language):
                i18n.use(language)
                self.assertEqual(spec.name, "TMDB (Movies & Series — by director / studio)")
                self.assertEqual(spec.category, "Creator-search upgrades (optional)")
                self.assertEqual(field.label, "Username")
                self.assertEqual(field.env_key, "OPENSUBTITLES_USERNAME")
                self.assertEqual(field.file_key, "opensubtitles_username")
                self.assertEqual(field.display_label(), i18n.t("Username"))
                self.assertEqual(spec.display_name(), i18n.t(spec.name))
                for credential_id in ("qbittorrent", "opensubtitles", "rutracker", "online_fix"):
                    proper = get_credential_spec(credential_id)
                    self.assertEqual(proper.display_name(), proper.name)

    def test_translated_menu_displays_status_without_changing_row_values(self):
        i18n.use("pt-BR")
        with patch.object(credentials, "get_credential", return_value=None), \
             patch.object(credentials, "storage_problem", return_value=""), \
             patch.object(ui, "arrow_select", return_value=None) as select:
            ui.credentials_menu()
        rows = [row for row in select.call_args.args[0] if row.value in CREDENTIAL_REGISTRY]
        self.assertEqual([row.value for row in rows], list(CREDENTIAL_REGISTRY))
        self.assertTrue(all(row.hint == "não definido" for row in rows))
        self.assertEqual(select.call_args.kwargs["title"], "Credenciais")

    def test_inline_confirmation_accepts_portuguese_only_in_portuguese(self):
        for language in ("en", "pt-BR", "qps"):
            i18n.use(language)
            for answer in ("y", " Y ", "yes", "Yes", "s", " S ", "sim", "Sim", "n", "não", "no", "other"):
                with self.subTest(language=language, answer=answer), \
                     patch.object(ui.console, "input", return_value=answer):
                    expected = answer.strip().lower() in ("y", "yes") or (
                        language == "pt-BR" and answer.strip().lower() in ("s", "sim"))
                    self.assertEqual(ui._inline_confirm("confirm?"), expected)
            with patch.object(ui.console, "input", return_value=""):
                self.assertFalse(ui._inline_confirm("confirm?"))
                self.assertTrue(ui._inline_confirm("confirm?", default=True))
            for error in (EOFError, KeyboardInterrupt):
                with patch.object(ui.console, "input", side_effect=error):
                    self.assertFalse(ui._inline_confirm("confirm?", default=True))

    def test_credential_secret_stays_hidden_with_translated_labels(self):
        field = get_credential_spec("opensubtitles").fields[1]
        for language in ("pt-BR", "qps"):
            with self.subTest(language=language), \
                 patch.object(credentials, "get_credential", return_value="test-only-password"), \
                 patch.object(credentials, "credential_source", return_value="file"):
                i18n.use(language)
                hidden = ui._view_field_label(field, False)
                self.assertNotIn("test-only-password", hidden)
                self.assertIn("********", hidden)
                self.assertIn(field.display_label(), hidden)
                self.assertIn("test-only-password", ui._view_field_label(field, True))

    def test_missing_field_verification_uses_translated_singular_and_plural(self):
        i18n.use("pt-BR")
        spec = get_credential_spec("opensubtitles")
        self.assertEqual(spec.verify({"OPENSUBTITLES_USERNAME": "fixture"}),
                         (False, "campo obrigatório ausente: Senha"))
        self.assertEqual(spec.verify({}), (False, "campos obrigatórios ausentes: Usuário, Senha"))

    def test_storage_failure_is_translated_when_read_after_language_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.json"
            path.write_text("{broken", encoding="utf-8")
            with patch.object(credentials, "_CRED_FILE", path), \
                 patch.object(credentials, "_LEGACY_CRED_PATHS", []), \
                 patch.object(credentials, "_file_cache", None), \
                 patch.object(credentials, "_file_problem", ""):
                for language in ("en", "pt-BR", "qps"):
                    i18n.use(language)
                    expected = i18n.t("Cannot read or migrate credentials to {path}. Existing files were preserved.",
                                      path=path)
                    self.assertEqual(credentials.storage_problem(), expected)
                    self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_client_submission_status_and_protocol_values_are_not_translated(self):
        payload = qbittorrent.TorrentPayload("a" * 40, "magnet:?xt=urn:btih:" + "a" * 40)
        for language in ("pt-BR", "qps"):
            for existing, confirmed, identity in ((True, True, "already in client"),
                                                  (False, True, "added to client"),
                                                  (False, False, "submitted; confirmation pending")):
                with self.subTest(language=language, status=identity):
                    i18n.use(language)
                    client = qbittorrent.Client("http://localhost:8080", session=Mock())
                    with patch.object(client, "torrents", side_effect=[[{}] if existing else [],
                                                                      [{}] if confirmed else []]), \
                         patch.object(client, "_request", return_value=Mock(text="Ok.")) as request:
                        self.assertEqual(client.add(payload, "/downloads", "Back"), identity)
                    if existing:
                        request.assert_not_called()
                    else:
                        request.assert_called_once_with("POST", "torrents/add", data={
                            "category": "Back", "autoTMM": "false", "savepath": "/downloads",
                            "urls": payload.magnet}, files=None)

    def test_progress_translates_labels_and_preserves_client_data(self):
        row = {"name": "Back", "state": "stalledDL", "category": "Settings", "save_path": "/Back"}
        for language in ("pt-BR", "qps"):
            with self.subTest(language=language):
                i18n.use(language)
                text = client_ui.progress_text(row)
                self.assertEqual(text.splitlines()[0], "Back")
                for value in ("stalledDL", "Settings", "/Back"):
                    self.assertIn(value, text)
                self.assertIn(i18n.t("Progress: {progress} • Client state: {state}",
                                     progress="0.0%", state="stalledDL"), text)


class NetworkPrivacyI18nTests(unittest.TestCase):
    INFO = {"query": "203.0.113.7", "isp": "Example ISP", "org": "Example Org",
            "as": "AS64500 Example", "city": "São Paulo", "country": "Brazil"}

    def setUp(self):
        self.addCleanup(security._exposure.update, state=None)

    def draw(self, info, keys, width=120, height=40, force=False):
        outputs = []
        screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)

        def capture(_banner, frame):
            with screen.capture() as result:
                screen.print(frame)
            outputs.append(result.get())

        with patch.object(security, "console", screen), \
             patch.object(security, "_fetch_network_info", return_value=info), \
             patch.object(security, "_render", side_effect=capture), \
             patch.object(security, "load_setting", return_value=False), \
             patch.object(security, "save_setting") as save, \
             patch.dict(security.os.environ, {"TORRENT_SKIP_WARNING": ""}), \
             patch.object(security.readchar, "readkey", side_effect=keys), \
             patch("sys.stdout", io.StringIO()):
            result = security.show_security_warning(force=force)
        return result, outputs, save

    def test_ip_and_location_are_masked_until_r_and_hidden_again_in_both_locales(self):
        for language in ("pt-BR", "qps"):
            for width, height in ((80, 24), (120, 40)):
                with self.subTest(language=language, size=(width, height)):
                    i18n.use(language)
                    result, outputs, _ = self.draw(self.INFO, ["R", "r", "\r"], width, height)
                    self.assertTrue(result)
                    self.assertEqual([self.INFO["query"] in frame for frame in outputs], [False, True, False])
                    self.assertEqual(["São Paulo, Brazil" in frame for frame in outputs], [False, True, False])
                    self.assertIn(security.mask_ip(self.INFO["query"]), outputs[0])
                    self.assertIn(security.mask_text("São Paulo, Brazil"), outputs[0])
                    self.assertIn(i18n.t("Public IP"), outputs[0])
                    self.assertIn(i18n.t("Location"), outputs[0])
                    self.assertIn(i18n.t("R reveal"), outputs[0])
                    self.assertIn(i18n.t("R hide"), outputs[1])
                    self.assertTrue(all(len(frame.rstrip().splitlines()) <= height for frame in outputs))

    def test_each_verdict_uses_api_state_before_display_translation(self):
        cases = (
            ({"proxy": True, "hosting": True, "mobile": True}, "vpn",
             "✓ Proxy/VPN flagged by network database."),
            ({"hosting": True, "mobile": True}, "vpn",
             "✓ Hosting/datacenter IP — likely a VPN exit (not a residential ISP)."),
            ({"org": "Mullvad VPN", "mobile": True}, "vpn",
             "✓ VPN provider name detected in network org."),
            ({"mobile": True}, "exposed", "! Mobile carrier IP — no VPN. Carrier and peers see this IP."),
            ({}, "exposed", "! Residential ISP IP — no VPN detected. Your real IP is visible."),
        )
        for language in ("pt-BR", "qps"):
            i18n.use(language)
            for updates, state, message in cases:
                with self.subTest(language=language, state=state, updates=updates):
                    _, outputs, _ = self.draw(self.INFO | updates, ["\r"], width=200, height=50)
                    self.assertEqual(security.exposure(), state)
                    self.assertIn(i18n.t(message), outputs[0])
                    badge = "[good]VPN[/good]" if state == "vpn" else "[warn]IP visible[/warn]"
                    self.assertEqual(security.exposure_label(), i18n.t(badge))
            security._exposure["state"] = "vpn"
            _, outputs, _ = self.draw(None, ["\r"])
            self.assertIsNone(security.exposure())
            self.assertEqual(security.exposure_label(), "")
            self.assertIn(i18n.t("Could not fetch public IP info (offline?)."), outputs[0])

    def test_dismiss_and_abort_keys_keep_their_identity(self):
        for language in ("pt-BR", "qps"):
            i18n.use(language)
            result, _, save = self.draw(self.INFO, ["D"])
            self.assertTrue(result)
            save.assert_called_once_with("security_warning_dismissed", True)
            self.assertFalse(self.draw(self.INFO, [readchar.key.ESC])[0])


class TerminalAdvisoryI18nTests(unittest.TestCase):
    def test_legacy_and_dumb_advisories_translate_but_remain_ascii(self):
        for language in ("en", "pt-BR", "qps"):
            for legacy in (True, False):
                with self.subTest(language=language, legacy=legacy), ExitStack() as stack:
                    i18n.use(language)
                    screen = Console(file=io.StringIO(), width=160, color_system=None)
                    stack.enter_context(patch.object(terminal_check, "console", screen))
                    stack.enter_context(patch.object(type(screen), "is_terminal", new_callable=PropertyMock,
                                                    return_value=True))
                    stack.enter_context(patch.object(type(screen), "is_dumb_terminal", new_callable=PropertyMock,
                                                    return_value=not legacy))
                    stack.enter_context(patch.object(screen, "legacy_windows", legacy))
                    stack.enter_context(patch.object(terminal_check.readchar, "readkey", return_value="x"))
                    terminal_check.advise_limited_terminal()
                    output = screen.file.getvalue()
                    self.assertTrue(output.isascii())
                    if language == "pt-BR":
                        self.assertIn("Pressione qualquer tecla", output)
                        self.assertIn("Este console" if legacy else "Este terminal", output)
                    if legacy:
                        self.assertIn(terminal_check._WINGET_CMD, output)
                        self.assertIn(terminal_check._REG_CMD, output)
                    else:
                        self.assertIn("TERM=dumb", output)


if __name__ == "__main__":
    unittest.main()
