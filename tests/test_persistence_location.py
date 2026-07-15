import json
import os
import tempfile
import unittest
from unittest.mock import patch

from torrent_finder import constants, store


class MachineStatePathTests(unittest.TestCase):
    def test_windows_machine_state_dir_ignores_localappdata_changes(self):
        home = os.path.join("C:\\", "Users", "test-user")

        with patch.object(constants.sys, "platform", "win32"), \
             patch.object(constants.os.path, "expanduser", return_value=home), \
             patch.dict(os.environ, {"LOCALAPPDATA": "C:\\network-a"}):
            first = constants.machine_state_dir()

        with patch.object(constants.sys, "platform", "win32"), \
             patch.object(constants.os.path, "expanduser", return_value=home), \
             patch.dict(os.environ, {"LOCALAPPDATA": "D:\\network-b"}):
            second = constants.machine_state_dir()

        expected = os.path.join(home, ".torrent-finder-cli")
        self.assertEqual(first, expected)
        self.assertEqual(second, expected)


class LegacyStateMigrationTests(unittest.TestCase):
    def test_initial_load_merges_stranded_state_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            older_path = os.path.join(tmp, "repo-state.json")
            newer_path = os.path.join(tmp, "runtime-state.json")
            target_path = os.path.join(tmp, "machine", "filter_state.json")

            older = {
                "settings": {"quiet_mode": False, "download_dir": "old"},
                "providers": {"movies": {"engines": {"Apibay": True}}},
                "history": [
                    self._history("shared", "2026-06-01T12:00:00+00:00"),
                    self._history("older", "2026-05-01T12:00:00+00:00"),
                ],
                "stats": {
                    "first_use": "2026-05-01T12:00:00+00:00",
                    "session_count": 100,
                    "searches_total": 90,
                    "method_picks": {"aria": 10},
                },
            }
            newer = {
                "settings": {"quiet_mode": True, "download_dir": "new"},
                "providers": {"movies": {"engines": {"Nyaa": True}}},
                "history": [
                    self._history("shared", "2026-07-01T12:00:00+00:00"),
                    self._history("newer", "2026-06-15T12:00:00+00:00"),
                ],
                "stats": {
                    "first_use": "2026-06-01T12:00:00+00:00",
                    "session_count": 24,
                    "searches_total": 12,
                    "method_picks": {"aria": 2, "webtorrent": 3},
                },
            }
            self._write(older_path, older)
            self._write(newer_path, newer)
            os.utime(older_path, (1, 1))
            os.utime(newer_path, (2, 2))

            merged = store._load_initial_state(target_path, [older_path, newer_path])

            self.assertTrue(os.path.isfile(target_path))
            self.assertEqual(merged["settings"], newer["settings"])
            self.assertEqual(merged["providers"], newer["providers"])
            self.assertEqual(
                [entry["query"] for entry in merged["history"]],
                ["shared", "newer", "older"],
            )
            self.assertEqual(merged["stats"]["first_use"], older["stats"]["first_use"])
            self.assertEqual(merged["stats"]["session_count"], 100)
            self.assertEqual(merged["stats"]["searches_total"], 90)
            self.assertEqual(
                merged["stats"]["method_picks"],
                {"aria": 10, "webtorrent": 3},
            )

    def test_existing_machine_state_is_authoritative(self):
        with tempfile.TemporaryDirectory() as tmp:
            target_path = os.path.join(tmp, "machine-state.json")
            legacy_path = os.path.join(tmp, "legacy-state.json")
            current = {"history": [], "stats": {}}
            self._write(target_path, current)
            self._write(legacy_path, {
                "history": [self._history("must-not-return", "2026-01-01T00:00:00+00:00")],
                "stats": {"session_count": 99},
            })

            loaded = store._load_initial_state(target_path, [legacy_path])

            self.assertEqual(loaded, current)

    @staticmethod
    def _history(query, timestamp):
        return {
            "query": query,
            "provider": "movies",
            "timestamp": timestamp,
            "presets": [],
        }

    @staticmethod
    def _write(path, data):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)


if __name__ == "__main__":
    unittest.main()
