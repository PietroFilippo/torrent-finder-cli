import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from torrent_finder import main, state, store
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.manga_provider import MangaProvider
from torrent_finder.providers.combined_provider import CombinedProvider, CombinedResults
from torrent_finder.search_profiles import ProfileLibrary


class ProfileTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "filter_state.json"
        for attr, value in (("STATE_PATH", str(self.path)), ("LEGACY_STATE_PATHS", []),
                            ("_cache", None), ("_dirty", False), ("_atexit_registered", True)):
            mocked = patch.object(store, attr, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.anime, self.manga = AnimeProvider(), MangaProvider()

    def provider(self):
        return CombinedProvider([self.anime, self.manga])

    def restart(self):
        store._cache, store._dirty = None, False
        return self.provider()

    def test_legacy_profile_migrates_without_changing_solo_or_other_settings(self):
        legacy = {"selected": ["anime"], "providers": {"anime": {
            "active_presets": ["1080p"], "engine_modes": {"Nyaa": "off", "Knaben": "on"}}},
            "shared": {"include_keywords": ["batch"], "exclude_keywords": ["sample"]}}
        original = {"settings": {"combined_search": legacy, "download_dir": "custom"},
                    "providers": {"anime": {"active_presets": ["720p"]}}, "stats": {"sessions": 19}}
        self.path.write_text(json.dumps(original), encoding="utf-8")
        provider = self.provider()
        self.assertEqual(provider.children[0].active_presets[0].name, "1080p")
        self.assertEqual(provider.children[0].engines[0].mode, "off")
        self.assertEqual(provider.selected_slugs, {"anime"})
        self.assertEqual(json.loads(self.path.read_text()), original)  # read/cancel never writes
        provider.save_profile()
        reloaded = self.restart()
        self.assertEqual(reloaded.snapshot(), provider.snapshot())
        self.assertEqual(reloaded.profile_name, "Default")
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["providers"], original["providers"])
        self.assertEqual(saved["stats"], original["stats"])
        self.assertEqual(saved["settings"]["download_dir"], "custom")

    def test_named_profiles_round_trip_their_own_settings(self):
        provider = self.provider()
        library = provider.profile_draft()
        defaults = provider.snapshot()
        provider.children[0].preferred_presets = [provider.children[0].presets[1]]
        provider.children[1].active_presets = [provider.children[1].presets[0]]
        provider.children[0].engines[0].set_mode("off")
        provider.shared_filters.exclude_keywords = ["sample"]
        provider.selected_slugs = {"anime", "manga"}
        provider.result_sort = "newest"
        library.create("Anime + Manga", provider.snapshot())
        provider.save_profile(library)
        restored = self.restart()
        self.assertEqual(restored.snapshot(), provider.snapshot())
        self.assertEqual(restored.profile_name, "Anime + Manga")
        restored.use_profile(ProfileLibrary.load().find("DEFAULT"))
        self.assertEqual(restored.snapshot(), defaults)
        self.assertEqual(self.anime.preferred_presets, [])
        self.assertEqual(self.anime.engines[0].mode, "on")

    def test_copy_and_rename_keep_identity_without_shared_mutable_settings(self):
        library = self.provider().profile_draft()
        original = library.current
        copied = library.create("Older anime", original["settings"])
        self.assertNotEqual(copied["id"], original["id"])
        copied["settings"]["selected"] = ["anime"]
        copied["settings"]["providers"]["anime"]["active_presets"].append("1080p")
        library.rename(copied["id"], "  Older Anime [test]  ")
        self.assertEqual(library.current["id"], copied["id"])
        self.assertEqual(library.current["name"], "Older Anime [test]")
        self.assertEqual(original["settings"]["selected"], ["anime", "manga"])
        self.assertEqual(original["settings"]["providers"]["anime"]["active_presets"], [])

    def test_invalid_names_leave_draft_unchanged(self):
        library = self.provider().profile_draft()
        for name in ("", "  ", "DEFAULT", " default ", "x" * 61, "line\nbreak", "a\x1bb"):
            with self.subTest(name=repr(name)), self.assertRaises(ValueError):
                library.create(name, {})
            self.assertEqual(len(library.entries), 1)
        library.rename("default", "DEFAULT")  # case-only rename of itself is legal
        self.assertEqual(library.current["name"], "DEFAULT")

    def test_delete_active_selects_remaining_profile_and_cannot_delete_last(self):
        provider = self.provider()
        library = provider.profile_draft()
        added = library.create("Second", provider.snapshot())
        library.delete(added["id"])
        self.assertEqual(library.current["name"], "Default")
        with self.assertRaises(ValueError):
            library.delete("default")
        library.save()
        self.assertEqual(len(ProfileLibrary.load().entries), 1)

    def test_empty_provider_selection_is_rejected_before_any_write(self):
        library = self.provider().profile_draft()
        library.current["settings"]["selected"] = []
        library.create("Valid", {"selected": ["anime"]})
        with self.assertRaisesRegex(ValueError, "Default"):
            library.save()
        self.assertFalse(self.path.exists())

    def test_history_snapshot_does_not_overwrite_saved_profile(self):
        provider = self.provider()
        provider.save_profile()
        before = self.path.read_bytes()
        history = provider.snapshot()
        history["selected"] = ["manga"]
        history["result_sort"] = "size"
        with patch.object(main, "get_provider", return_value=provider):
            main._history_pick({"provider": "all", "query": "Example", "search_profile": history})
        self.assertIsNone(provider.profile_id)
        self.assertEqual(provider.result_sort, "size")
        self.assertEqual(self.path.read_bytes(), before)
        provider.save_profile()
        library = ProfileLibrary.load()
        self.assertEqual(library.find("Default")["settings"]["selected"], ["anime", "manga"])
        self.assertEqual(library.current["settings"]["selected"], ["manga"])
        self.assertEqual(library.current["name"], "History search")

    def test_unknown_stored_version_and_corrupt_library_never_replace_saved_data(self):
        for saved in ({"version": 2}, {"version": 1, "profiles": []},
                      {"version": 1, "active": "missing", "profiles": [
                          {"id": "id", "name": "Name", "settings": {}}]},
                      {"version": 1, "active": [], "profiles": [
                          {"id": "id", "name": "Name", "settings": {}}]}):
            state.save_setting("search_profiles", saved)
            store.flush()
            before = self.path.read_bytes()
            with self.assertRaises(ValueError):
                ProfileLibrary.load()
            self.assertEqual(before, self.path.read_bytes())

    def test_cli_invalid_profile_fails_before_security_or_update_network_calls(self):
        for argv in (["--profile", "Missing"], ["--profile", "Default", "-t", "anime"]):
            with patch("sys.stderr", io.StringIO()), patch.object(main, "show_security_warning") as warning, \
                 patch.object(main, "check_for_update") as update, patch.object(main, "load_state"):
                with self.assertRaises(SystemExit) as error:
                    main._main_loop(main._build_parser().parse_args(argv))
                self.assertEqual(error.exception.code, 2)
                warning.assert_not_called()
                update.assert_not_called()

    def test_cli_profile_and_provider_override_remain_session_only(self):
        provider = self.provider()
        provider.save_profile()
        library = provider.profile_draft()
        library.create("Older Anime", {"selected": ["anime"], "result_sort": "newest"})
        library.save()
        before = self.path.read_bytes()
        args = main._build_parser().parse_args(["--profile", "older anime", "--providers", "manga", "-q", "Example", "-y"])
        with patch.object(main, "get_provider", side_effect=lambda name: provider if name == "all" else self.manga), \
             patch.object(main, "load_state"), patch.object(main, "console"), \
             patch.object(main, "advise_limited_terminal"), patch.object(main, "check_for_update", return_value=None), \
             patch.object(main, "consume_update_report", return_value=None), \
             patch.object(main, "start_esc_listener", return_value=threading.Event()), \
             patch.object(main, "record_search"), patch.object(state, "add_history_entry"), \
             patch.object(main, "browse_results", return_value="next"), \
             patch.object(main, "_handle_whats_next", return_value="EXIT"), patch.object(main, "_goodbye"), \
             patch.object(provider, "search_many", return_value=CombinedResults([{"name": "Example"}])):
            main._main_loop(args)
        self.assertEqual(provider.selected_slugs, {"manga"})
        self.assertEqual(provider.result_sort, "newest")
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
