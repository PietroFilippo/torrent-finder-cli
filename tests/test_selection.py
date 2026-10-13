"""The shared selection callbacks, exercised with both menus' real policies."""

import unittest
from unittest.mock import patch

import isolation  # noqa: F401  # redirects persistence before the menus load it
from torrent_finder.providers.base import SearchEngine
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.torrent_meta import TorrentFile
from torrent_finder.ui import prompts, theme
from torrent_finder.ui.selection import MultiSelection


class SelectionChecks:
    def capture(self, call):
        def select(items, **kwargs):
            self.items = items
            self.keys = kwargs["key_actions"]
            self.action = kwargs["on_action"]
            self.selection = self.keys["v"].__self__
            self.assertIsInstance(self.selection, MultiSelection)
            self.indexes = list(self.selection.indexes)
            return None

        with patch.object(prompts, "arrow_select", side_effect=select):
            call()

    def states(self):
        return [item.toggle_state if item.toggle_states else item.toggled for item in self.items]

    def test_all_and_invert_skip_disabled_rows_and_actions(self):
        disabled = self.indexes[1]
        self.items[disabled].enabled = False
        for key in ("a", "A", "i", "I"):
            before = self.states()
            self.assertIs(self.keys[key](len(self.items) - 1, self.items), True)
            after = self.states()
            for i in range(len(self.items)):
                if i not in self.indexes or i == disabled:
                    self.assertEqual(after[i], before[i])
                elif key.lower() == "a":
                    self.assertEqual(after[i], self.on(i))
                else:
                    self.assertEqual(after[i], self.off(i) if before[i] != self.off(i) else self.on(i))

    def test_clear_includes_disabled_rows_and_preserves_engines(self):
        for key in ("c", "C"):
            self.keys["a"](0, self.items)
            self.items[self.indexes[-1]].enabled = False
            before = self.states()
            self.assertIs(self.keys[key](0, self.items), True)
            for i in self.indexes:
                expected = before[i] if i in self.engines else self.off(i)
                self.assertEqual(self.states()[i], expected)

    def test_space_uses_the_policy_and_ignores_other_or_disabled_rows(self):
        for i in self.indexes:
            item = self.items[i]
            before = self.states()[i]
            expected = (item.toggle_states[(item.toggle_states.index(before) + 1) % len(item.toggle_states)]
                        if item.toggle_states else not before)
            self.assertIs(self.keys[" "](i, self.items), True)
            self.assertEqual(self.states()[i], expected)
            item.enabled = False
            self.keys[" "](i, self.items)
            self.assertEqual(self.states()[i], expected)
        before = self.states()
        for i in set(range(len(self.items))) - set(self.indexes):
            self.keys[" "](i, self.items)
        self.assertEqual(self.states(), before)

    def test_anchor_moves_without_toggling_and_ignores_action_rows(self):
        first, last = self.indexes[0], self.indexes[-1]
        before = self.states()
        self.assertIs(self.keys["v"](first, self.items), True)
        self.assertEqual(self.items[first].marker, theme.MARKER)
        self.keys["v"](last, self.items)
        self.assertEqual(self.items[first].marker, "")
        self.assertEqual(self.selection.anchor, last)
        self.assertEqual(self.items[last].marker, theme.MARKER)
        self.keys["v"](len(self.items) - 1, self.items)
        self.assertEqual(self.selection.anchor, last)
        self.assertEqual(self.states(), before)

    def test_range_without_anchor_sets_one_and_second_press_flips_it(self):
        first = self.indexes[0]
        self.keys["V"](len(self.items) - 1, self.items)
        self.assertIsNone(self.selection.anchor)
        before = self.states()
        self.keys["V"](first, self.items)
        self.assertEqual(self.states(), before)
        self.assertEqual(self.selection.anchor, first)
        self.keys["V"](first, self.items)
        self.assertEqual(self.states()[first], self.off(first) if before[first] == self.on(first) else self.on(first))
        self.assertIsNone(self.selection.anchor)
        self.assertEqual(self.items[first].marker, "")

    def test_ranges_are_inclusive_skip_disabled_rows_and_can_end_on_actions(self):
        first, last = self.indexes[0], self.indexes[-1]
        disabled = self.indexes[1]
        self.items[disabled].enabled = False
        for anchor, end in ((first, len(self.items) - 1), (last, 0)):
            self.keys["a"](0, self.items)
            before = self.states()
            self.keys["v"](anchor, self.items)
            self.assertIs(self.keys["V"](end, self.items), True)
            after = self.states()
            lo, hi = sorted((anchor, end))
            for i in range(len(self.items)):
                expected = self.off(i) if i in self.indexes and i != disabled and lo <= i <= hi else before[i]
                self.assertEqual(after[i], expected)
            self.assertIsNone(self.selection.anchor)
            self.assertEqual(self.items[anchor].marker, "")

    def test_range_reads_current_anchor_state_after_bulk_changes(self):
        first, last = self.indexes[0], self.indexes[-1]
        for key in ("a", "i", "c"):
            self.keys["v"](last, self.items)
            self.keys[key](0, self.items)
            self.assertEqual(self.selection.anchor, last)
            self.assertEqual(self.items[last].marker, theme.MARKER)
            target = self.states()[last] == self.off(last)
            self.keys["V"](first, self.items)
            for i in self.indexes:
                self.assertEqual(self.states()[i], self.on(i) if target else self.off(i))

    def test_disabled_row_can_be_an_anchor_but_range_does_not_change_it(self):
        first, last = self.indexes[0], self.indexes[-1]
        self.items[first].enabled = False
        before = self.states()[first]
        self.keys["v"](first, self.items)
        self.assertEqual(self.selection.anchor, first)
        self.keys["V"](last, self.items)
        self.assertEqual(self.states()[first], before)
        self.assertIsNone(self.selection.anchor)

    def test_save_returns_confirm_index_without_changing_state_or_anchor(self):
        self.keys["v"](self.indexes[0], self.items)
        before = self.states()
        for key in ("w", "W"):
            result = self.keys[key](0, self.items)
            self.assertIs(type(result), int)
            self.assertEqual(self.items[result].value, "confirm")
            self.assertEqual(self.states(), before)
            self.assertEqual(self.selection.anchor, self.indexes[0])


class FilterSelectionTests(SelectionChecks, unittest.TestCase):
    def setUp(self):
        self.provider = MovieProvider()
        self.provider.engines = [
            SearchEngine("Primary", "", lambda _: []),
            SearchEngine("Backup", "", lambda _: [], enabled=False, emergency_fallback=True),
            SearchEngine("Off", "", lambda _: [], enabled=False),
        ]
        self.capture(lambda: prompts.filter_menu(self.provider))
        self.engines = [i for i in self.indexes if self.items[i].value[0] == "engine"]
        self.presets = [i for i in self.indexes if self.items[i].value[0] == "preset"]

    def on(self, i):
        return "On" if i in self.engines else "Require"

    def off(self, i):
        return "Off"

    def test_auto_inverts_to_on_prefer_inverts_to_off(self):
        backup, preset = self.engines[1], self.presets[0]
        self.items[preset].toggle_state = "Prefer"
        self.keys["i"](0, self.items)
        self.assertEqual([self.items[i].toggle_state for i in self.engines], ["Off", "On", "On"])
        self.assertEqual(self.items[preset].toggle_state, "Off")

    def test_auto_and_prefer_anchor_states_keep_distinct_range_targets(self):
        backup, preset = self.engines[1], self.presets[0]
        self.keys["v"](backup, self.items)
        self.keys["V"](preset, self.items)
        self.assertEqual(self.items[backup].toggle_state, "On")
        self.assertEqual(self.items[preset].toggle_state, "Require")
        self.items[preset].toggle_state = "Prefer"
        self.keys["v"](preset, self.items)
        self.keys["V"](backup, self.items)
        self.assertEqual(self.items[backup].toggle_state, "Off")
        self.assertEqual(self.items[preset].toggle_state, "Off")

    def test_clear_action_preserves_auto_and_clears_prefer(self):
        preset = self.presets[0]
        self.items[preset].toggle_state = "Prefer"
        clear = next(i for i, item in enumerate(self.items) if item.value == "clear")
        self.assertIs(self.action(clear, self.items), True)
        self.assertEqual(self.items[self.engines[1]].toggle_state, "Auto")
        self.assertEqual(self.items[preset].toggle_state, "Off")
        self.assertIs(self.action(self.selection.confirm_index, self.items), False)

    def test_boolean_fallback_keeps_invert_and_range_rules(self):
        i = self.presets[0]
        item = self.items[i]
        item.toggle_states = ()
        self.keys["a"](0, self.items)
        self.assertTrue(item.toggled)
        self.keys["i"](0, self.items)
        self.assertFalse(item.toggled)
        item.toggle_state = "Off"
        self.keys["v"](i, self.items)
        self.keys["V"](i, self.items)
        self.assertTrue(item.toggled)


class FileSelectionTests(SelectionChecks, unittest.TestCase):
    def setUp(self):
        self.files = [TorrentFile(7, "Show - 01.mkv", 100),
                      TorrentFile(2, "Show - 02.mkv", 200),
                      TorrentFile(11, "Show - 03.mkv", 300)]
        self.capture(lambda: prompts.episode_select_prompt(self.files, preselected=[7, 11]))
        self.engines = []

    def on(self, i):
        return True

    def off(self, i):
        return False

    def test_action_buttons_use_the_same_bulk_callbacks(self):
        for value, key in (("all", "a"), ("invert", "i"), ("clear", "c")):
            idx = next(i for i, item in enumerate(self.items) if item.value == value)
            before = [item.toggled for item in self.items]
            self.assertIs(self.action(idx, self.items), True)
            after = [item.toggled for item in self.items]
            for item, state in zip(self.items, before):
                item.toggled = state
            self.keys[key](idx, self.items)
            self.assertEqual([item.toggled for item in self.items], after)
        self.assertIs(self.action(self.selection.confirm_index, self.items), False)

    def test_save_returns_file_ids_and_empty_save_clears_selection(self):
        def select(items, **kwargs):
            return kwargs["key_actions"]["w"](0, items)
        with patch.object(prompts, "arrow_select", side_effect=select):
            self.assertEqual(prompts.episode_select_prompt(self.files, [7, 11]), [7, 11])
            self.assertEqual(prompts.episode_select_prompt(self.files), [])

    def test_cancel_after_edits_keeps_the_callers_previous_selection(self):
        previous = [7, 11]
        def select(items, **kwargs):
            kwargs["key_actions"]["c"](0, items)
            return None
        with patch.object(prompts, "arrow_select", side_effect=select):
            self.assertIsNone(prompts.episode_select_prompt(self.files, previous))
        self.assertEqual(previous, [7, 11])


if __name__ == "__main__":
    unittest.main()
