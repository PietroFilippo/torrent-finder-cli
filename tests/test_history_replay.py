"""History replay uses recorded preset identities without changing saved filters."""

import unittest
import threading
from contextlib import ExitStack
from unittest.mock import patch

import isolation  # noqa: F401
from isolation import isolate_store

from rich.text import Text

from torrent_finder import i18n, main, state, store
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.combined_provider import CombinedProvider
from torrent_finder.ui import chrome, history, theme
from torrent_finder.ui.selector import key_pairs


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.provider = AnimeProvider()
        self.presets = {p.name: p for p in self.provider.presets}
        self.provider.active_presets = [self.presets["720p"]]
        self.path = isolate_store(self)
        state.save_state([self.provider])
        self.saved = self.path.read_bytes()
        self.entry = {"provider": "anime", "query": "Frieren", "presets": ["1080p"]}

    def pick(self, entry=None):
        with patch.object(main, "get_provider", return_value=self.provider), \
             patch.object(store, "commit") as commit, patch.object(store, "update") as update:
            result = main._history_pick(self.entry if entry is None else entry)
        commit.assert_not_called()
        update.assert_not_called()
        self.assertEqual(self.path.read_bytes(), self.saved)
        return result

    def test_enter_uses_saved_presets_without_changing_current_or_saved_filters(self):
        replay, facet, query = self.pick()
        self.assertEqual([p.name for p in replay.active_presets], ["1080p"])
        self.assertEqual([p.name for p in self.provider.active_presets], ["720p"])
        self.assertIsNone(facet)
        self.assertEqual(query, "Frieren")

    def test_c_keeps_current_filters_and_has_no_notice(self):
        replay, _, _ = self.pick(dict(self.entry, _history_current_filters=True))
        self.assertIs(replay, self.provider)
        self.assertEqual([p.name for p in replay.active_presets], ["720p"])
        self.assertEqual(main._history_notice(replay), "")

    def test_same_presets_are_silent_regardless_of_order(self):
        self.provider.active_presets = [self.presets["1080p"], self.presets["720p"]]
        replay, _, _ = self.pick(dict(self.entry, presets=["720p", "1080p"]))
        with patch.object(chrome, "announce") as announce:
            for design in ("quiet", "citrinitas"):
                theme.apply(design)
                self.assertEqual(main._history_notice(replay, "Other notice"), "Other notice")
        announce.assert_not_called()

    def test_changed_presets_use_the_designs_notice_line(self):
        replay, _, _ = self.pick()
        expected = "Using the filters from then: 1080p. Your saved filters are unchanged."
        for design in ("quiet", "citrinitas"):
            with self.subTest(design=design), patch.object(chrome, "announce") as announce, \
                 patch.object(main, "_browse_results", return_value="back") as browse:
                theme.apply(design)
                self.assertEqual(main.browse_results(replay, [], note="Other notice"), "back")
                if theme.FRAMED:
                    announce.assert_called_once_with(expected)
                    self.assertEqual(browse.call_args.kwargs["note"], "Other notice")
                else:
                    announce.assert_not_called()
                    self.assertEqual(browse.call_args.kwargs["note"], expected + "\nOther notice")

    def test_missing_presets_are_skipped_and_named_even_if_effective_filters_match(self):
        replay, _, _ = self.pick(dict(self.entry, presets=["720p", "Old [red] preset"]))
        self.assertEqual(replay.active_presets, [self.presets["720p"]])
        note = Text.from_markup(main._history_notice(replay)).plain
        self.assertIn("skipped missing filters: Old [red] preset", note)
        self.assertIn("720p", note)

    def test_empty_and_entirely_missing_presets_do_not_fall_back_to_current_filters(self):
        for names in ([], ["Removed"]):
            with self.subTest(names=names):
                replay, _, _ = self.pick(dict(self.entry, presets=names))
                self.assertEqual(replay.active_presets, [])
                self.assertIn("No presets", main._history_notice(replay))

    def test_other_settings_and_preset_identities_stay_current_in_portuguese(self):
        self.provider.engines[0].set_mode("off")
        self.provider.preferred_presets = [next(p for p in self.provider.presets if p.name not in {"720p", "1080p"})]
        self.provider.result_sort = "size"
        self.provider.name_rules.exclude_words = "sample"
        before = state.provider_snapshot(self.provider)
        i18n.use("pt-BR")
        replay, _, _ = self.pick()
        after = state.provider_snapshot(replay)
        after["active_presets"] = before["active_presets"]
        self.assertEqual(after, before)
        self.assertIn("Usando os filtros de antes: 1080p", main._history_notice(replay))

    def test_aliases_creator_facet_and_missing_provider_keep_their_routing(self):
        aliases = ["Frieren", "Sousou no Frieren"]
        replay, facet, value = self.pick(dict(self.entry, queries=aliases))
        self.assertEqual(value, aliases)
        self.assertIsNone(facet)
        creator = self.provider.creator_facets[0]
        replay, facet, value = self.pick(dict(self.entry, kind="creator", facet=creator.key, name="Name"))
        self.assertIs(facet, creator)
        self.assertEqual(value, "Name")
        self.assertEqual(replay.active_presets, [self.presets["1080p"]])
        with patch.object(main, "get_provider", return_value=None):
            self.assertEqual(main._history_pick(self.entry), (None, None, "Frieren"))

    def test_combined_enter_still_restores_snapshot_in_memory_and_c_leaves_it_current(self):
        combined = CombinedProvider([self.provider])
        combined.restore({"selected": ["anime"]})
        snapshot = combined.snapshot()
        snapshot["providers"]["anime"]["active_presets"] = ["1080p"]
        entry = dict(self.entry, provider="all", search_profile=snapshot)
        before = combined.snapshot()
        with patch.object(main, "get_provider", return_value=combined), \
             patch.object(store, "commit") as commit, patch.object(store, "update") as update:
            current, _, _ = main._history_pick(dict(entry, _history_current_filters=True))
            self.assertEqual(current.snapshot(), before)
            replay, _, _ = main._history_pick(entry)
        self.assertIs(replay, combined)
        self.assertEqual(replay.snapshot(), snapshot)
        self.assertIsNone(replay.profile_id)
        commit.assert_not_called()
        update.assert_not_called()
        self.assertEqual(self.path.read_bytes(), self.saved)

    def test_whats_next_search_returns_to_current_filters(self):
        replay, _, _ = self.pick()
        with patch.object(main, "search_again_prompt", return_value="search"), patch.object(main, "clear_screen"):
            self.assertEqual(main._handle_whats_next(replay), (None, self.provider, None, None))

    def test_main_search_and_next_search_use_replay_then_current_filters(self):
        searched = []

        def search(provider, queries, *args, **kwargs):
            searched.append([p.name for p in provider.active_presets])
            return [{"name": "Frieren", "source": "Nyaa"}]

        with ExitStack() as stack:
            stack.enter_context(patch("sys.argv", ["torrent", "-y", "--theme", "quiet"]))
            for name in ("console", "advise_limited_terminal", "clear_screen", "load_state",
                         "remove_moved_launchers", "_offer_language_once", "record_search", "_goodbye",
                         "ProgressScreen", "make_search_screen_renderer"):
                stack.enter_context(patch.object(main, name))
            stack.enter_context(patch.object(main, "get_provider", return_value=self.provider))
            stack.enter_context(patch.object(main, "provider_select_prompt", return_value=("history", self.entry)))
            stack.enter_context(patch.object(main, "get_query_with_shortcut", return_value="Next search"))
            stack.enter_context(patch.object(main, "check_for_update", return_value=None))
            stack.enter_context(patch.object(main, "consume_update_report", return_value=None))
            stack.enter_context(patch.object(main, "start_esc_listener", return_value=threading.Event()))
            stack.enter_context(patch.object(main, "_handle_whats_next", return_value="EXIT"))
            stack.enter_context(patch("torrent_finder.search_session.search_many", side_effect=search))
            recorded = stack.enter_context(patch.object(state, "add_history_entry"))
            browse = stack.enter_context(patch.object(main, "_browse_results", side_effect=["back", "next"]))
            main._main_loop()
        self.assertEqual(searched, [["1080p"], ["720p"]])
        self.assertEqual([call.args[2] for call in recorded.call_args_list], [["1080p"], ["720p"]])
        self.assertIn("Using the filters from then: 1080p", browse.call_args_list[0].kwargs["note"])
        self.assertEqual(browse.call_args_list[1].kwargs["note"], "")
        self.assertEqual(self.path.read_bytes(), self.saved)


class HistoryKeysTests(unittest.TestCase):
    def test_enter_and_both_c_keys_select_without_mutating_the_entry(self):
        entry = {"provider": "anime", "query": "Frieren", "presets": ["1080p"]}
        for key in (None, "c", "C"):
            with self.subTest(key=key):
                def select(items, **kwargs):
                    pairs = dict(key_pairs(kwargs["footer"]()))
                    self.assertEqual(pairs["Enter"], "saved filters")
                    self.assertEqual(pairs["C"], "current filters")
                    if key:
                        self.assertIs(kwargs["key_actions"][key](len(items) - 1, items), True)
                        return kwargs["key_actions"][key](0, items)
                    return 0

                with patch.object(history, "load_history", return_value=[entry]), \
                     patch.object(history, "arrow_select", side_effect=select):
                    selected = history.history_select_prompt()
                self.assertEqual(bool(selected.get("_history_current_filters")), bool(key))
                self.assertNotIn("_history_current_filters", entry)


if __name__ == "__main__":
    unittest.main()
