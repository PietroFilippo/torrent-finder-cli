import json
import os
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import Mock, patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from torrent_finder import credentials
from torrent_finder.credential_registry import (
    CREDENTIAL_REGISTRY,
    CredentialField,
    CredentialSpec,
    credential_file_keys,
    get_credential_spec,
)


class CredentialRegistryTests(unittest.TestCase):
    def test_registry_contains_every_existing_integration_with_unique_fields(self):
        self.assertEqual(
            tuple(spec.id for spec in CREDENTIAL_REGISTRY),
            (
                "opensubtitles",
                "addic7ed",
                "jimaku",
                "rutracker",
                "online_fix",
                "madokami",
                "tmdb",
                "igdb",
            ),
        )

        fields = [field.env_key for spec in CREDENTIAL_REGISTRY for field in spec.fields]
        self.assertEqual(len(fields), len(set(fields)))
        self.assertEqual(
            credential_file_keys(),
            {env_key: env_key.lower() for env_key in fields},
        )

    def test_registry_lookup_and_optional_opensubtitles_api_key(self):
        spec = get_credential_spec("opensubtitles")

        self.assertIsNotNone(spec)
        self.assertEqual(
            tuple(field.env_key for field in spec.required_fields),
            ("OPENSUBTITLES_USERNAME", "OPENSUBTITLES_PASSWORD"),
        )
        self.assertFalse(spec.fields[-1].required)
        self.assertIsNone(get_credential_spec("missing"))

    def test_spec_resolves_entered_values_before_existing_values(self):
        spec = get_credential_spec("igdb")
        existing = {
            "IGDB_CLIENT_ID": "old-id",
            "IGDB_CLIENT_SECRET": "old-secret",
        }

        with patch(
            "torrent_finder.credentials.get_credential",
            side_effect=lambda key: existing.get(key),
        ):
            effective = spec.effective_values({"IGDB_CLIENT_ID": "new-id"})

        self.assertEqual(effective["IGDB_CLIENT_ID"], "new-id")
        self.assertEqual(effective["IGDB_CLIENT_SECRET"], "old-secret")
        self.assertEqual(spec.missing_required(effective), ())

    def test_spec_rejects_missing_required_fields_before_verifier(self):
        verifier = Mock(return_value=(True, "unexpected"))
        spec = CredentialSpec(
            id="test",
            category="Test",
            icon="?",
            name="Test",
            fields=(CredentialField("TEST_KEY", "Key"),),
            verifier=verifier,
        )

        self.assertEqual(spec.verify({}), (False, "missing required field(s): Key"))
        verifier.assert_not_called()

    def test_status_distinguishes_missing_file_and_environment_values(self):
        spec = get_credential_spec("tmdb")

        with patch("torrent_finder.credentials.get_credential", return_value=None):
            self.assertEqual(spec.status(), "not set")
        with patch("torrent_finder.credentials.get_credential", return_value="key"), \
             patch("torrent_finder.credentials.credential_source", return_value="file"):
            self.assertEqual(spec.status(), "saved")
        with patch("torrent_finder.credentials.get_credential", return_value="key"), \
             patch("torrent_finder.credentials.credential_source", return_value="env"):
            self.assertEqual(spec.status(), "set via environment")


class CredentialVerifierTests(unittest.TestCase):
    def test_each_registry_entry_dispatches_to_its_verifier_adapter(self):
        cases = (
            (
                "opensubtitles",
                "torrent_finder.subtitles.test_opensubtitles",
                ("OPENSUBTITLES_USERNAME", "OPENSUBTITLES_PASSWORD", "OPENSUBTITLES_APIKEY"),
            ),
            (
                "addic7ed",
                "torrent_finder.subtitles.test_addic7ed",
                ("ADDIC7ED_USERNAME", "ADDIC7ED_PASSWORD"),
            ),
            ("jimaku", "torrent_finder.jimaku.validate_key", ("JIMAKU_API_KEY",)),
            (
                "rutracker",
                "torrent_finder.rutracker.test_credentials",
                ("RUTRACKER_USERNAME", "RUTRACKER_PASSWORD"),
            ),
            (
                "online_fix",
                "torrent_finder.online_fix.test_credentials",
                ("ONLINE_FIX_USERNAME", "ONLINE_FIX_PASSWORD"),
            ),
            (
                "madokami",
                "torrent_finder.madokami.test_credentials",
                ("MADOKAMI_USERNAME", "MADOKAMI_PASSWORD"),
            ),
            ("tmdb", "torrent_finder.resolvers.tmdb.test_api_key", ("TMDB_API_KEY",)),
            (
                "igdb",
                "torrent_finder.resolvers.igdb.test_credentials",
                ("IGDB_CLIENT_ID", "IGDB_CLIENT_SECRET"),
            ),
        )

        for credential_id, target, ordered_keys in cases:
            with self.subTest(credential_id=credential_id):
                spec = get_credential_spec(credential_id)
                effective = {
                    field.env_key: f"value-{index}"
                    for index, field in enumerate(spec.fields)
                }
                with patch(target, return_value=(True, "verified")) as verifier:
                    self.assertEqual(spec.verify(effective), (True, "verified"))
                verifier.assert_called_once_with(*(effective[key] for key in ordered_keys))


class CredentialStorageTests(unittest.TestCase):
    def test_registry_save_and_clear_use_derived_file_keys(self):
        spec = get_credential_spec("tmdb")
        all_env_keys = {
            field.env_key: ""
            for entry in CREDENTIAL_REGISTRY
            for field in entry.fields
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "credentials.json"
            with patch.object(credentials, "_CRED_FILE", path), \
                 patch.object(credentials, "_file_cache", None), \
                 patch.dict(os.environ, all_env_keys, clear=False):
                spec.save({"TMDB_API_KEY": "  saved-key  "})

                self.assertEqual(credentials.get_credential("TMDB_API_KEY"), "saved-key")
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {
                    "tmdb_api_key": "saved-key"
                })

                spec.clear_saved()
                self.assertIsNone(credentials.get_credential("TMDB_API_KEY"))
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {})


class CredentialMenuTests(unittest.TestCase):
    def test_menu_rows_are_derived_from_the_registry(self):
        from torrent_finder.ui import credentials as credentials_ui

        with patch.object(credentials_ui, "arrow_select", return_value=None) as select:
            credentials_ui.credentials_menu()

        items = select.call_args.args[0]
        rendered_specs = [item.value for item in items if isinstance(item.value, CredentialSpec)]
        self.assertEqual(rendered_specs, list(CREDENTIAL_REGISTRY))


if __name__ == "__main__":
    unittest.main()
