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
        provider.engines[1].explicitly_disabled = True
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


if __name__ == "__main__":
    unittest.main()
