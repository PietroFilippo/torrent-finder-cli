import unittest
from unittest.mock import patch

from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder import state


class FallbackStateProvider(BaseProvider):
    name = "Fallback"
    slug = "fallback"
    icon = "?"
    categories = []

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


class EngineFallbackStateTests(unittest.TestCase):
    def test_auto_is_the_default_mode_for_a_fallback_capable_engine(self):
        provider = FallbackStateProvider()

        self.assertEqual(provider.engines[0].mode, "on")
        self.assertEqual(provider.engines[1].mode, "auto")

        provider.engines[1].set_mode("off")
        self.assertEqual(provider.engines[1].mode, "off")
        provider.engines[1].set_mode("on")
        self.assertEqual(provider.engines[1].mode, "on")

    def test_explicit_engine_modes_are_loaded(self):
        provider = FallbackStateProvider()
        saved = {
            "providers": {
                "fallback": {
                    "engine_modes": {"Primary": "off", "Backup": "on"},
                    "engines": {"Primary": True, "Backup": False},
                    "explicitly_disabled_engines": ["Backup"],
                    "active_presets": [],
                }
            }
        }

        with patch("torrent_finder.state.store.read", return_value=saved):
            state.load_state([provider])

        self.assertEqual(provider.engines[0].mode, "off")
        self.assertEqual(provider.engines[1].mode, "on")

    def test_explicit_disable_metadata_is_loaded(self):
        provider = FallbackStateProvider()
        saved = {
            "providers": {
                "fallback": {
                    "engines": {"Primary": True, "Backup": False},
                    "explicitly_disabled_engines": ["Backup"],
                    "active_presets": [],
                }
            }
        }

        with patch("torrent_finder.state.store.read", return_value=saved):
            state.load_state([provider])

        self.assertTrue(provider.engines[1].explicitly_disabled)

    def test_legacy_disabled_engine_is_treated_as_explicit(self):
        provider = FallbackStateProvider()
        saved = {
            "providers": {
                "fallback": {
                    "engines": {"Primary": True, "Backup": False},
                    "active_presets": [],
                }
            }
        }

        with patch("torrent_finder.state.store.read", return_value=saved):
            state.load_state([provider])

        self.assertTrue(provider.engines[1].explicitly_disabled)

    def test_save_state_preserves_explicit_disable_metadata(self):
        provider = FallbackStateProvider()
        provider.engines[1].set_mode("off")
        persisted = {}

        with (
            patch("torrent_finder.state.store.read", return_value={}),
            patch(
                "torrent_finder.state.store.write",
                side_effect=lambda data: persisted.update(data),
            ),
            patch("torrent_finder.state.store.flush"),
        ):
            state.save_state([provider])

        self.assertEqual(
            persisted["providers"]["fallback"]["explicitly_disabled_engines"],
            ["Backup"],
        )
        self.assertEqual(
            persisted["providers"]["fallback"]["engine_modes"],
            {"Primary": "on", "Backup": "off"},
        )


if __name__ == "__main__":
    unittest.main()
