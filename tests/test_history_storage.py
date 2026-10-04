"""Long search history: 2,000 entries, each combined-search profile stored once."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from torrent_finder import settings_backup, state, store
from isolation import isolate_store, restart_store

PROFILE = {"selected": ["anime", "manga"], "providers": {"anime": {"active_presets": ["1080p"]}},
           "shared": {"include_keywords": [], "exclude_keywords": ["sample"]}, "result_sort": "relevance"}
OTHER = dict(PROFILE, selected=["manga"])


def entry(number, **extra):
    return {"query": f"Search {number}", "provider": "anime",
            "timestamp": f"2026-09-{1 + number % 28:02d}T10:00:00+00:00", "presets": [], **extra}


class HistoryStorageTests(unittest.TestCase):
    def saved(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_keeps_two_thousand_newest_distinct_searches(self):
        self.path = isolate_store(self, {"history": [entry(i) for i in range(store.HISTORY_LIMIT)]})
        state.add_history_entry("Newest", "anime")
        store.flush()
        history = self.saved()["history"]
        self.assertEqual(len(history), store.HISTORY_LIMIT)
        self.assertEqual((history[0]["query"], history[-1]["query"]), ("Newest", f"Search {store.HISTORY_LIMIT - 2}"))

    def test_identical_profiles_are_stored_once_and_expanded_on_read(self):
        self.path = isolate_store(self)
        for query, profile in (("Saki", PROFILE), ("Saki Achiga", PROFILE), ("Nana", OTHER), ("Plain", None)):
            state.add_history_entry(query, "all" if profile else "anime", search_profile=profile)
        store.flush()
        saved = self.saved()
        self.assertEqual(len(saved["history_profiles"]), 2)
        self.assertTrue(all("search_profile" not in e for e in saved["history"]))
        history = state.load_history()
        self.assertEqual([e.get("search_profile") for e in history], [None, OTHER, PROFILE, PROFILE])
        self.assertTrue(all("search_profile_id" not in e for e in history))
        history[1]["search_profile"]["selected"].append("changed")  # a copy, not the saved snapshot
        self.assertEqual(state.load_history()[1]["search_profile"], OTHER)

    def test_unreferenced_profiles_are_dropped(self):
        old = [dict(entry(i), provider="all", search_profile=OTHER) for i in range(1)]
        rest = [entry(i) for i in range(1, store.HISTORY_LIMIT)]
        self.path = isolate_store(self, {"history": rest + old})  # the profile entry is the oldest
        state.add_history_entry("Combined", "all", search_profile=PROFILE)
        store.flush()
        self.assertEqual(list(self.saved()["history_profiles"].values()), [PROFILE])
        state.clear_history()
        self.assertNotIn("history_profiles", self.saved())

    def test_older_inline_files_still_read_and_are_compacted_on_the_next_search(self):
        self.path = isolate_store(self, {"history": [entry(1, provider="all", search_profile=PROFILE)]})
        self.assertEqual(state.load_history()[0]["search_profile"], PROFILE)
        state.add_history_entry("Next", "anime")
        store.flush()
        saved = self.saved()
        self.assertEqual(saved["history"][1]["search_profile_id"], list(saved["history_profiles"])[0])

    def test_backups_carry_full_entries_and_imports_compact_them(self):
        self.path = isolate_store(self)
        state.add_history_entry("Saki", "all", search_profile=PROFILE)
        store.flush()
        export = Path(tempfile.mkdtemp()) / "backup.json"
        settings_backup.export_settings(export, history=True)
        exported = settings_backup.read_backup(export)["history"]
        self.assertEqual(exported[0]["search_profile"], PROFILE)
        self.assertNotIn("search_profile_id", exported[0])

        state.clear_history()
        store.commit(settings_backup.import_change({"history": exported}, "merge"))
        saved = self.saved()
        self.assertEqual(list(saved["history_profiles"].values()), [PROFILE])
        self.assertEqual(state.load_history()[0]["search_profile"], PROFILE)

    def test_two_thousand_entries_with_many_combined_searches_stay_small(self):
        big_profile = dict(PROFILE, providers={slug: {"engine_modes": {f"Engine {n}": "on" for n in range(20)},
                                                       "active_presets": [f"Preset {n}" for n in range(10)]}
                                               for slug in ("anime", "manga", "movies", "games", "books")})
        rows = [entry(i, provider="all", search_profile=big_profile) if i % 3 == 0 else entry(i)
                for i in range(store.HISTORY_LIMIT - 1)]
        self.path = isolate_store(self, {"history": rows})
        restart_store()
        state.add_history_entry("Newest", "all", search_profile=big_profile)
        store.flush()
        self.assertLess(os.path.getsize(self.path), 1024 * 1024)
        self.assertEqual(len(self.saved()["history_profiles"]), 1)


if __name__ == "__main__":
    unittest.main()
