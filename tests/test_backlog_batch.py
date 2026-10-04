import io
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import readchar
from rich.console import Console, Group
from rich.text import Text

from torrent_finder import bookmarks, credentials, settings_backup as backup, store
from torrent_finder.name_rules import NameRules
from torrent_finder.providers import PROVIDERS
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.manga_provider import MangaProvider
from torrent_finder.providers.combined_provider import CombinedProvider
from torrent_finder.providers.base import SearchEngine
from torrent_finder.search_result import SearchResult
from torrent_finder.search_profiles import ProfileLibrary
from torrent_finder.state import provider_snapshot, apply_provider_state
from torrent_finder.result_details import detail_lines
from torrent_finder.language_tags import has_brazilian_subtitles
from torrent_finder.ui import table, prompts, theme, backup as backup_ui
from isolation import isolate_store, restart_store


class IsolatedState(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = isolate_store(self, path=self.root / "state.json")
        for owner, key, value in ((credentials, "_CRED_FILE", self.root / "credentials.json"),
                                  (credentials, "_LEGACY_CRED_PATHS", []), (credentials, "_file_cache", None)):
            mock = patch.object(owner, key, value)
            mock.start()
            self.addCleanup(mock.stop)


class BackupTests(IsolatedState):
    def initial(self):
        profile = CombinedProvider([AnimeProvider()])
        profile.restore({"selected": ["anime"]})
        profile.name_rules = NameRules(all_words="Saki", exclude_words="sample")
        data = {"providers": {"anime": provider_snapshot(AnimeProvider())},
                "settings": {"combined_search": profile.snapshot(), "download_dir": "D:/Downloads",
                             "hide_stream_output": True, "last_update_check": 123, "launcher_alias": "private",
                             "password": "DO-NOT-EXPORT"},
                "history": [{"query": "Saki", "provider": "anime", "timestamp": "2026-10-01T09:30:00+00:00"}],
                "bookmarks": [], "stats": {"total_searches": 7}}
        store.commit(data)
        return data

    def test_export_allowlist_optional_history_and_round_trip(self):
        self.initial()
        for include in (False, True):
            path = self.root / f"backup-{include}.json"
            backup.export_settings(path, history=include)
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("DO-NOT-EXPORT", content)
            self.assertNotIn("last_update_check", content)
            data = backup.read_backup(path)
            self.assertEqual("history" in data, include)
            candidate, preview = backup.prepare_import(data, "replace")
            store.commit(candidate)
            self.assertEqual(store.read()["stats"]["total_searches"], 7)
            self.assertEqual(store.read()["settings"]["combined_search"]["name_rules"]["all_words"], "Saki")
            self.assertIn("Credentials are separate", " ".join(preview))

    def test_profile_merge_matches_names_retains_ids_and_active(self):
        self.initial()
        library = ProfileLibrary.load()
        library.create("Laptop", {"selected": ["anime"]})
        library.save()
        laptop_id = library.current["id"]
        incoming = deepcopy(library.data)
        incoming["profiles"][1]["id"] = "remote-id"
        incoming["profiles"][1]["settings"]["result_sort"] = "newest"
        incoming["active"] = "remote-id"
        incoming["profiles"].append({"id": "default", "name": "Bad duplicate", "settings": {}})
        with self.assertRaises(ValueError):
            backup.prepare_import({"settings": {"search_profiles": incoming}})
        incoming["profiles"].pop()
        incoming["profiles"].append({"id": "third", "name": "New profile", "settings": {"selected": ["manga"]}})
        candidate, preview = backup.prepare_import({"settings": {"search_profiles": incoming}})
        merged = ProfileLibrary(candidate["settings"]["search_profiles"])
        self.assertEqual(merged.current["id"], laptop_id)
        self.assertEqual(merged.current["settings"]["result_sort"], "newest")
        self.assertEqual(len(merged.entries), 3)
        self.assertEqual(ProfileLibrary.load().current["settings"].get("result_sort"), None)
        self.assertIn("Replace profile: Laptop", preview)

    def test_legacy_combined_backup_updates_default_profile_in_named_library(self):
        self.initial()
        library = ProfileLibrary.load()
        library.save()
        candidate, _ = backup.prepare_import({"settings": {"combined_search": {"selected": ["manga"]}}})
        restored = ProfileLibrary(candidate["settings"]["search_profiles"])
        self.assertEqual(restored.find("Default")["settings"]["selected"], ["manga"])

    def test_runtime_reload_resets_provider_settings_omitted_by_replace(self):
        from torrent_finder.state import reload_state
        provider = AnimeProvider()
        provider.nyaa_category = "1_4"
        provider.name_rules = NameRules(phrase="Old")
        provider.engines[0].set_mode("off")
        store.commit({"providers": {}})
        reload_state([provider])
        self.assertEqual(provider.nyaa_category, "1_2")
        self.assertEqual(provider.name_rules.phrase, "")
        self.assertEqual(provider.engines[0].mode, "on")

    def test_replace_preserves_unrelated_data_and_omitted_history(self):
        initial = self.initial()
        result, _ = backup.prepare_import({"settings": {"hide_stream_output": False}}, "replace")
        self.assertEqual(result["providers"], {})
        self.assertNotIn("download_dir", result["settings"])
        self.assertEqual(result["settings"]["launcher_alias"], "private")
        self.assertEqual(result["history"], initial["history"])
        result, _ = backup.prepare_import({"history": []}, "replace")
        self.assertEqual(result["history"], [])

    def test_malformed_nested_backup_and_failed_replace_preserve_bytes_and_cache(self):
        initial = self.initial()
        before = self.path.read_bytes()
        cases = [{"settings": {"password": "bad"}}, {"providers": {"anime": {"active_presets": "1080p"}}},
                 {"settings": {"combined_search": {"selected": []}}},
                 {"history": [{"query": [], "provider": "anime", "timestamp": "x"}]},
                 {"providers": {"anime": {"name_rules": {"phrase": []}}}}]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValueError):
                backup.prepare_import(data)
        with patch.object(store.os, "replace", side_effect=OSError("disk failure")), self.assertRaises(OSError):
            store.commit({"settings": {}})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(store.read(), initial)
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_corrupt_authoritative_file_is_never_overwritten_by_import_or_migration(self):
        self.path.write_text("{broken", encoding="utf-8")
        legacy = self.root / "legacy.json"
        legacy.write_text('{"settings":{}}', encoding="utf-8")
        self.assertEqual(store._load_initial_state(str(self.path), [str(legacy)]), {})
        with self.assertRaises(ValueError):
            store.commit({})
        self.assertEqual(self.path.read_text(), "{broken")

    def test_export_refuses_existing_path_and_wrong_import_type(self):
        self.initial()
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            backup.export_settings(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        target = self.root / "wrong.json"
        target.write_text('{"format":"torrent-finder-credentials","version":1,"data":{}}')
        with self.assertRaises(ValueError):
            backup.read_backup(target)

    def test_separate_credential_transfer_excludes_env_and_preserves_on_failure(self):
        credentials.save_credentials({"RUTRACKER_USERNAME": "saved-user", "RUTRACKER_PASSWORD": "saved-pass"})
        path = self.root / "secrets.json"
        with patch.dict("os.environ", {"RUTRACKER_PASSWORD": "environment-secret"}):
            backup.export_credentials(path)
        self.assertNotIn("environment-secret", path.read_text())
        values = backup.read_backup(path, credentials=True)
        credentials.import_file_values(values, replace=True)
        old = credentials._CRED_FILE.read_bytes()
        with patch.object(credentials.os, "replace", side_effect=OSError("failure")), self.assertRaises(OSError):
            credentials.import_file_values({"RUTRACKER_PASSWORD": "new"}, replace=True)
        self.assertEqual(credentials._CRED_FILE.read_bytes(), old)

    def test_import_preview_cancel_is_read_only(self):
        self.initial()
        path = self.root / "backup.json"
        backup.export_settings(path)
        old = self.path.read_bytes()
        actions = iter(["import", "replace", "cancel", "back"])
        def choose(items, **kwargs):
            action = next(actions)
            return next(i for i, item in enumerate(items) if item.value == action)
        with patch.object(backup_ui, "arrow_select", side_effect=choose), \
             patch.object(prompts, "get_query_with_shortcut", return_value=str(path)):
            self.assertFalse(backup_ui.backup_menu())
        self.assertEqual(self.path.read_bytes(), old)


class BookmarkTests(IsolatedState):
    def test_all_acquisition_handles_persist_without_resolution(self):
        provider = AnimeProvider()
        provider.last_queries = ["Example"]
        rows = [dict(name="Magnet", source="Nyaa", info_hash="a" * 40),
                dict(name="Manga", source="Madokami", info_hash="mdk:1", mdk_path="/manga/a.cbz"),
                dict(name="Book", source="Libgen", info_hash="lg:1", lg_md5="123"),
                dict(name="Game", source="FitGirl", info_hash="fg:1", fg_post_url="https://example.test/game"),
                dict(name="Forum", source="RuTracker", info_hash="rt:1", rt_topic_id="42")]
        bookmarks.save_results(provider, rows)
        bookmarks.save_results(provider, rows)
        self.assertEqual(len(bookmarks.entries()), len(rows))
        restart_store()
        for saved, row in zip(bookmarks.entries(), rows):
            for key, value in row.items():
                self.assertEqual(saved["result"][key], value)
            self.assertEqual(saved["queries"], ["Example"])
            self.assertTrue(saved["fetched_at"])
        self.assertNotIn("provider_slug", rows[0])

    def test_refresh_only_changes_matching_identity_and_retains_unreturned_listing(self):
        provider = AnimeProvider()
        original = dict(name="Example", source="Nyaa", info_hash="a" * 40, seeders=5, fetched_at="2020-01-01")
        bookmarks.save_results(provider, [original])
        identity = bookmarks.entries()[0]["id"]
        bookmarks.refresh(identity, [dict(original, info_hash="b" * 40)])
        missing = bookmarks.entries()[0]
        self.assertEqual(missing["fetched_at"], "2020-01-01")
        self.assertIn("retained", missing["refresh_status"])
        bookmarks.refresh(identity, [dict(original, seeders=10, fetched_at="2026-10-02")])
        self.assertEqual(bookmarks.entries()[0]["result"]["seeders"], 10)
        self.assertEqual(bookmarks.entries()[0]["fetched_at"], "2026-10-02")
        self.assertEqual(bookmarks.entries()[0]["result"]["provider_slug"], "anime")
        bookmarks.remove(identity)
        self.assertEqual(bookmarks.entries(), [])

    def test_search_snapshot_is_independent_and_restores_category_rules(self):
        provider = AnimeProvider()
        provider.nyaa_category = "1_3"
        provider.name_rules = NameRules(phrase="Example Title")
        bookmarks.save_search(provider, "Example")
        provider.name_rules.phrase = "Changed"
        restored = bookmarks.search_provider(bookmarks.entries()[0])
        self.assertEqual(restored.nyaa_category, "1_3")
        self.assertEqual(restored.name_rules.phrase, "Example Title")

    def test_creator_bookmark_uses_work_context_instead_of_previous_keyword_search(self):
        provider = AnimeProvider()
        provider.last_queries = ["Unrelated previous query"]
        bookmarks.save_results(provider, [dict(name="Example 720p", from_work="Example", info_hash="a" * 40)])
        self.assertEqual(bookmarks.entries()[0]["queries"], ["Example"])

    def test_malformed_bookmarks_are_preserved(self):
        store.commit({"bookmarks": [{"id": "a", "kind": "result"}]})
        old = self.path.read_bytes()
        with self.assertRaises(ValueError):
            bookmarks.save_search(AnimeProvider(), "New")
        self.assertEqual(self.path.read_bytes(), old)

    def test_save_failure_keeps_existing_collection(self):
        bookmarks.save_search(AnimeProvider(), "First")
        with patch.object(store.os, "replace", side_effect=OSError("failure")), self.assertRaises(OSError):
            bookmarks.save_search(AnimeProvider(), "Second")
        self.assertEqual([e["name"] for e in bookmarks.entries()], ["First"])


class NameAndCategoryTests(unittest.TestCase):
    def test_normalized_literal_rules_and_word_boundaries(self):
        rules = NameRules(all_words="ação BATCH", any_words="1080p 720p", phrase="The Show", exclude_words="sample dub")
        self.assertTrue(rules.matches("[Group] The.Show Acao Batch 720p.mkv"))
        for name in ("The Other Show Acao Batch 720p", "The Show Acao Batch 480p", "The Show Acao Batch 720p sample"):
            self.assertFalse(rules.matches(name))
        self.assertTrue(NameRules(exclude_words="dub").matches("Dublin"))
        self.assertTrue(NameRules().matches("何も"))

    def test_rules_apply_identically_to_each_provider_without_matching_source(self):
        for template in PROVIDERS:
            if template.slug == "all":
                continue
            provider = type(template)()
            provider.default_filters = None
            provider.name_rules = NameRules(all_words="example", any_words="720p 1080p", exclude_words="sample")
            rows = [SearchResult(name="Example 720p", info_hash="a" * 40),
                    SearchResult(name="Other 720p", source="example", info_hash="b" * 40),
                    SearchResult(name="Example sample 1080p", info_hash="c" * 40)]
            with self.subTest(provider=provider.slug):
                found = provider._filter_search_results(rows, "example", None, None)
                self.assertEqual([r.info_hash for r in found], ["a" * 40])
                self.assertNotIn("fetched_at", rows[0])

    def test_shared_rules_before_alias_dedup_and_profile_round_trip(self):
        original = AnimeProvider()
        provider = CombinedProvider([original])
        provider.restore({"selected": ["anime"]})
        provider.name_rules = NameRules(all_words="720p")
        provider.children[0].nyaa_category = "1_4"
        with patch.object(AnimeProvider, "_init_engines", lambda p: [SearchEngine("Fixture", "", lambda q: [
            dict(name="Example 1080p", info_hash="a" * 40), dict(name="Example 720p", info_hash="a" * 40)])]):
            found = provider.search("Example")
        self.assertEqual([r.name for r in found], ["Example 720p"])
        restored = CombinedProvider([original])
        restored.restore(provider.snapshot())
        self.assertEqual(restored.children[0].nyaa_category, "1_4")
        self.assertEqual(restored.name_rules.all_words, "720p")

    def test_nyaa_categories_route_to_correct_source_scope(self):
        anime, manga = AnimeProvider(), MangaProvider()
        with patch.object(anime, "_search_nyaa_in", return_value=[]) as search:
            for code in anime.nyaa_categories:
                apply_provider_state(anime, {"nyaa_category": code})
                anime._search_nyaa("Example")
                search.assert_called_with("Example", code)
        with patch.object(manga, "_search_nyaa_in", return_value=[]) as search:
            manga._search_nyaa_raw("Example")
            search.assert_called_with("Example", "3_3")
            manga._search_nyaa_other("Example")
            search.assert_called_with("Example", "3_2")

    def test_category_and_rules_menu_cancel_discards_then_confirm_saves(self):
        provider = AnimeProvider()
        for save in (False, True):
            calls = iter(["rules", "category", "1_3", "confirm" if save else None])
            def choose(items, **kwargs):
                wanted = next(calls)
                return None if wanted is None else next(i for i, item in enumerate(items) if item.value == wanted)
            with patch.object(prompts, "arrow_select", side_effect=choose), \
                 patch("torrent_finder.ui.name_rules.edit_name_rules", return_value=NameRules(phrase="My Title")):
                prompts.filter_menu(provider, on_save=lambda: None)
            self.assertEqual(provider.nyaa_category, "1_3" if save else "1_2")
            self.assertEqual(provider.name_rules.phrase, "My Title" if save else "")

    def test_brazilian_subtitle_tags_do_not_accept_audio_or_ptpt(self):
        for name in ("Example Subs PT-BR", "Example PT_BR subtitles", "Example Legendas Português Brasileiro"):
            self.assertTrue(has_brazilian_subtitles(name), name)
        for name in ("Example Audio PT-BR", "Example Subs PT-PT", "Example Legendado", "Example Portuguese"):
            self.assertFalse(has_brazilian_subtitles(name), name)


class DetailsTests(unittest.TestCase):
    def test_expansion_restores_scroll_and_clamps_reverse_detail_scrolling(self):
        rows = [dict(name="Long Title " * 20) for _ in range(15)]
        screen = Console(file=io.StringIO(), width=40, height=16)
        keys = [readchar.key.DOWN] * 9 + ["i"] + ["]"] * 30 + ["[", "i", readchar.key.ENTER]
        frames = []
        real_build = table.build_table
        def build(*args, **kwargs):
            frames.append((args[1], args[2], kwargs.get("expanded"), kwargs.get("detail_offset")))
            return real_build(*args, **kwargs)
        with patch.object(table, "console", screen), patch.object(table, "build_table", side_effect=build), \
             patch.object(table.readchar, "readkey", side_effect=keys):
            self.assertEqual(table.interactive_select(rows), ("one", 9))
        closed = [frame for frame in frames if frame[0] == 9 and not frame[2]]
        self.assertEqual(closed[0][1], closed[-1][1])
        expanded = [frame for frame in frames if frame[2]]
        self.assertEqual(expanded[-1][3], expanded[-2][3] - 1)

    def test_metadata_and_filename_hints_are_distinct(self):
        lines = "\n".join(detail_lines(dict(name="[Team] Example 720p PT-BR Subs", resolution="1080p", uploader="Publisher")))
        self.assertIn("Resolution (listing): 1080p", lines)
        self.assertIn("Uploader (listing): Publisher", lines)
        self.assertIn("Filename hints: PT-BR subtitle tag", lines)
        self.assertNotIn("release group:", lines)
        self.assertIn("do not verify", lines)

    def test_expansion_and_bookmarking_preserve_sorted_selection(self):
        rows = [dict(name="Z title"), dict(name="A title")]
        screen = Console(file=io.StringIO(), width=40, height=16)
        saved = []
        keys = [readchar.key.DOWN, " ", "i", "]", "i", "b", readchar.key.ENTER]
        with patch.object(table, "console", screen), patch.object(table.readchar, "readkey", side_effect=keys):
            result = table.interactive_select(rows, initial_order="name", on_bookmark=lambda rs: saved.extend(rs) or "Saved")
        self.assertEqual(result, ("one", 0))
        self.assertEqual(saved, [rows[0]])

    def test_expanded_frame_fits_narrow_and_wide_terminals_with_long_metadata(self):
        rows = [dict(name="[Team] " + "Long Title " * 20 + "1080p", source="Nyaa", provider_label="Anime",
                     page_url="https://example.test/" + "a" * 100)]
        for width, height in ((40, 16), (60, 20), (80, 24), (128, 32)):
            for offset in (0, 10, 1000):
                with self.subTest(width=width, height=height, offset=offset):
                    screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
                    with patch.object(table, "console", screen):
                        screen.print(Group(theme.header(width=width), Text("Sort: Recommended"),
                                           table._note_preview("Saved listing; metadata may be stale"),
                                           table.build_table(rows, 0, 0, 1, 1, expanded=True, detail_offset=offset)))
                    output = screen.file.getvalue()
                    self.assertIn("Esc back", output)
                    self.assertLessEqual(len(output.splitlines()), height, output)
