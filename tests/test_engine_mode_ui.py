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


if __name__ == "__main__":
    unittest.main()
