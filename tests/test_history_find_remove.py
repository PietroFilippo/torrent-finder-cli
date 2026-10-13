"""Search history: / finds entries by text, x removes the focused one, u puts it back; both are saved at once."""

import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirects saved settings before anything reads them

from torrent_finder import state, store
from torrent_finder.ui import history as history_ui


def seed():
    state.clear_history()
    state.add_history_entry("elden ring", "games", [])
    state.add_history_entry("frieren", "anime", ["1080p"], search_profile={"providers": ["anime"]})
    state.add_history_entry("dune part two", "movies", [], queries=["dune part two", "dune 2"])
    store.flush()


def saved_queries() -> list[str]:
    return [entry["query"] for entry in store.read()["history"]]


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        seed()

    def test_remove_and_restore_are_operations_on_the_saved_list(self):
        entries = state.load_history()
        frieren = entries[1]
        state.remove_history_entry(frieren)
        self.assertEqual(saved_queries(), ["dune part two", "elden ring"])
        self.assertNotIn("history_profiles", store.read())  # the removed entry's profile went with it
        state.restore_history_entry(frieren, 1)
        self.assertEqual(saved_queries(), ["dune part two", "frieren", "elden ring"])
        self.assertEqual(state.load_history()[1]["search_profile"], {"providers": ["anime"]})

    def test_the_expanded_entry_matches_its_saved_form(self):
        saved = store.read()["history"][1]
        expanded = state.load_history()[1]
        self.assertIn("search_profile_id", saved)
        self.assertTrue(state.same_history_entry(saved, expanded))
        self.assertFalse(state.same_history_entry(saved, state.load_history()[0]))

    def test_a_failed_save_leaves_the_history_in_place(self):
        before = saved_queries()
        with patch.object(store, "commit", side_effect=store.SaveError("Couldn't save settings")):
            with self.assertRaises(store.SaveError):
                state.remove_history_entry(state.load_history()[0])
        self.assertEqual(saved_queries(), before)


class MenuTests(unittest.TestCase):
    """Drive the menu's key actions the way arrow_select calls them."""

    def setUp(self):
        seed()
        self.footers = []

    def run_menu(self, script):
        """*script*(items, keys, footer) acts on the live list; the fake selector then returns None."""
        def select(items, **kwargs):
            script(items, kwargs["key_actions"], kwargs["footer"], kwargs["title"])
            return None
        with patch.object(history_ui, "arrow_select", side_effect=select):
            history_ui.history_select_prompt()

    @staticmethod
    def labels(items):
        return [item.label for item in items if isinstance(item.value, dict)]

    def test_x_removes_the_focused_search_and_u_puts_it_back(self):
        seen = {}

        def script(items, keys, footer, title):
            self.assertEqual(self.labels(items), ["dune part two", "frieren", "elden ring"])
            self.assertIn("X remove", footer())
            self.assertNotIn("U undo", footer())
            outcome = keys["x"](1, items)
            self.assertEqual(self.labels(items), ["dune part two", "elden ring"])
            self.assertEqual(outcome, ("jump", 1))  # the cursor stays where the row was
            self.assertIn("Removed “frieren”", footer())
            self.assertIn("U undo", footer())
            seen["after_remove"] = saved_queries()
            self.assertEqual(keys["u"](1, items), ("jump", 1))
            self.assertEqual(self.labels(items), ["dune part two", "frieren", "elden ring"])
            self.assertIn("Put back “frieren”", footer())
            self.assertNotIn("U undo", footer())
            seen["after_undo"] = saved_queries()
        self.run_menu(script)
        self.assertEqual(seen["after_remove"], ["dune part two", "elden ring"])
        self.assertEqual(seen["after_undo"], ["dune part two", "frieren", "elden ring"])

    def test_delete_removes_too_and_x_on_an_action_row_does_nothing(self):
        import readchar

        def script(items, keys, footer, title):
            self.assertIs(keys[readchar.key.DELETE], keys["x"])
            back = next(i for i, item in enumerate(items) if item.value == "back")
            self.assertTrue(keys["x"](back, items))
            self.assertEqual(len(self.labels(items)), 3)
        self.run_menu(script)

    def test_a_failed_removal_keeps_the_row_and_says_so(self):
        def script(items, keys, footer, title):
            with patch.object(history_ui, "remove_history_entry", side_effect=store.SaveError("Couldn't save settings")):
                self.assertTrue(keys["x"](0, items))
            self.assertEqual(len(self.labels(items)), 3)
            self.assertIn("was not removed", footer())
        self.run_menu(script)
        self.assertEqual(len(saved_queries()), 3)

    def test_slash_filters_by_text_and_empty_text_clears_it(self):
        def script(items, keys, footer, title):
            with patch("torrent_finder.ui.prompts.get_query_with_shortcut", return_value="DUNE"):
                self.assertEqual(keys["/"](0, items), ("jump", 0))
            self.assertEqual(self.labels(items), ["dune part two"])
            self.assertIn('"DUNE"', title())
            self.assertIn("Search: DUNE", footer())
            with patch("torrent_finder.ui.prompts.get_query_with_shortcut", return_value="nothing here"):
                keys["/"](0, items)
            self.assertEqual(self.labels(items), [])
            self.assertIn("No searches contain “nothing here”", items[0].label)
            with patch("torrent_finder.ui.prompts.get_query_with_shortcut", return_value=""):
                keys["/"](0, items)
            self.assertEqual(len(self.labels(items)), 3)
            self.assertNotIn("Search:", footer())
            with patch("torrent_finder.ui.prompts.get_query_with_shortcut", return_value="GO_BACK"):
                self.assertTrue(keys["/"](0, items))
            self.assertEqual(len(self.labels(items)), 3)
        self.run_menu(script)

    def test_the_text_matches_saved_names_and_providers(self):
        entries = state.load_history()
        self.assertEqual([e["query"] for e in history_ui._filter_by_text(entries, "dune 2")], ["dune part two"])
        self.assertEqual([e["query"] for e in history_ui._filter_by_text(entries, "anime")], ["frieren"])
        self.assertEqual(history_ui._filter_by_text(entries, "  "), entries)


if __name__ == "__main__":
    unittest.main()
