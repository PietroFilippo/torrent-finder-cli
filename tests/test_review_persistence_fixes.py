"""Persistence fixes from the 2026-10-04 final review."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from isolation import isolate_store, restart_store
from torrent_finder import stats, store
from torrent_finder.search_profiles import ProfileError, ProfileLibrary
from torrent_finder.state import load_setting


class OddShapeTests(unittest.TestCase):
    def test_a_wrongly_shaped_stats_section_is_repaired_not_fatal(self):
        isolate_store(self, {"stats": {"searches_by_provider": 3, "total_searches": "many"}})
        stats.record_search("anime", "Saki", [])
        store.flush()
        saved = json.loads(Path(store.STATE_PATH).read_text(encoding="utf-8"))["stats"]
        self.assertEqual(saved["searches_by_provider"], {"anime": 1})

    def test_a_null_settings_section_reads_as_defaults(self):
        isolate_store(self, {"settings": None})
        self.assertEqual(load_setting("download_dir", "fallback"), "fallback")

    def test_one_change_that_no_longer_fits_does_not_block_later_saves(self):
        path = isolate_store(self, {})
        store.update(lambda data: data.setdefault("settings", {}).__setitem__("theme", "dark"))
        # Another window rewrites settings as a list; the pending change can't apply any more.
        path.write_text(json.dumps({"settings": ["odd"]}), encoding="utf-8")
        store.commit(lambda data: data.__setitem__("bookmarks", []))
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual((saved["bookmarks"], saved["settings"]), ([], ["odd"]))

    def test_an_explicit_save_on_an_odd_shape_is_a_value_error(self):
        isolate_store(self, {"settings": ["odd"]})
        with self.assertRaises(ValueError):
            store.commit(lambda data: data["settings"].update({"x": 1}))

    def test_a_settings_file_with_a_byte_order_mark_is_readable(self):
        path = isolate_store(self)
        path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"settings": {"theme": "dark"}}).encode("utf-8"))
        restart_store()
        self.assertIsNone(store.problem())
        self.assertEqual(load_setting("theme"), "dark")


class MigrationTests(unittest.TestCase):
    def test_a_file_another_window_created_meanwhile_wins_over_migration(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        target, legacy = os.path.join(folder.name, "state.json"), os.path.join(folder.name, "legacy.json")
        Path(legacy).write_text(json.dumps({"settings": {"theme": "old"}}), encoding="utf-8")
        real_read = store._read_document
        calls = []

        def read(path, patient=False):
            calls.append(path)
            if path == target and len([c for c in calls if c == target]) == 2:
                # Between the first look and the migration write, another window saves.
                Path(target).write_text(json.dumps({"bookmarks": [{"name": "new"}]}), encoding="utf-8")
            return real_read(path, patient=patient)
        with patch.object(store, "_read_document", side_effect=read):
            data, problem, unsaved = store._initial_load(target, [legacy])
        self.assertEqual(data, {"bookmarks": [{"name": "new"}]})
        self.assertEqual(json.loads(Path(target).read_text(encoding="utf-8")), {"bookmarks": [{"name": "new"}]})


def collection(*names, active="a"):
    return {"version": 1, "active": active,
            "profiles": [{"id": name.lower(), "name": name, "settings": {}} for name in names]}


class ProfileSaveTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self, {"settings": {"search_profiles": collection("A", "Discard")}})

    def test_a_stale_window_does_not_bring_back_a_deleted_profile(self):
        first, second = ProfileLibrary.load(), ProfileLibrary.load()
        second.delete("discard")
        second.save()
        first.update({"selected": ["anime"]})  # edits only profile A
        first.save()
        saved = load_setting("search_profiles")
        self.assertEqual([entry["name"] for entry in saved["profiles"]], ["A"])
        self.assertEqual(saved["profiles"][0]["settings"], {"selected": ["anime"]})

    def test_profiles_added_elsewhere_are_kept(self):
        first, second = ProfileLibrary.load(), ProfileLibrary.load()
        second.create("Movies night", {})
        second.save()
        first.rename("a", "Anime")
        first.save()
        self.assertEqual(sorted(entry["name"] for entry in load_setting("search_profiles")["profiles"]),
                         ["Anime", "Discard", "Movies night"])

    def test_conflicting_new_names_are_refused_with_a_clear_message(self):
        first, second = ProfileLibrary.load(), ProfileLibrary.load()
        second.create("Same", {})
        second.save()
        first.create("Same", {})
        with self.assertRaises(ProfileError) as caught:
            first.save()
        self.assertIn("Another window changed the profiles", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
