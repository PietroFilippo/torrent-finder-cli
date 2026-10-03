import unittest
from unittest.mock import patch

from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.ui import prompts
from torrent_finder.ui.selector import SelectItem


class ModeProvider(BaseProvider):
    name = "Modes"
    slug = "modes"
    icon = "?"
    categories = []
    presets = []

    def _init_engines(self):
        return [
            SearchEngine("Primary", "?", lambda query: [], enabled=True),
            SearchEngine(
                "Backup",
                "?",
                lambda query: [],
                enabled=False,
                emergency_fallback=True,
            ),
        ]


class EngineModeSelectorTests(unittest.TestCase):
    def test_select_item_cycles_explicit_states(self):
        item = SelectItem(
            "Backup",
            toggle_states=("On", "Auto", "Off"),
            toggle_state="Auto",
        )

        item.cycle_toggle()
        self.assertEqual(item.toggle_state, "Off")
        item.cycle_toggle()
        self.assertEqual(item.toggle_state, "On")

    def test_filter_menu_applies_the_selected_engine_mode(self):
        provider = ModeProvider()

        def choose(items, **_kwargs):
            backup = next(
                item
                for item in items
                if isinstance(item.value, tuple)
                and item.value[0] == "engine"
                and item.value[1].name == "Backup"
            )
            self.assertEqual(backup.toggle_state, "Auto")
            backup.toggle_state = "Off"
            return next(
                index for index, item in enumerate(items)
                if item.value == "confirm"
            )

        with (
            patch("torrent_finder.ui.prompts.arrow_select", side_effect=choose),
            patch("torrent_finder.state.save_state") as save_state,
        ):
            prompts.filter_menu(provider)

        self.assertEqual(provider.engines[1].mode, "off")
        save_state.assert_called_once()

    def test_invert_and_range_keep_auto_engine_shortcut_behavior(self):
        provider = ModeProvider()
        def choose(items, **kwargs):
            index = next(i for i, item in enumerate(items)
                         if isinstance(item.value, tuple) and item.value[1].name == "Backup")
            kwargs["key_actions"]["i"](index, items)
            self.assertEqual(items[index].toggle_state, "On")
            items[index].toggle_state = "Auto"
            kwargs["key_actions"]["v"](index, items)
            kwargs["key_actions"]["V"](index, items)
            self.assertEqual(items[index].toggle_state, "On")
            return None
        with patch.object(prompts, "arrow_select", side_effect=choose):
            prompts.filter_menu(provider)
        self.assertEqual(provider.engines[1].mode, "auto")


if __name__ == "__main__":
    unittest.main()
