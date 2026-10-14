import unittest

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from torrent_finder import state, store
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.book_provider import BookProvider
from torrent_finder.providers.game_provider import GameProvider
from torrent_finder.providers.manga_provider import MangaProvider
from torrent_finder.providers.mobile_provider import MobileProvider
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.providers.software_provider import SoftwareProvider


class KnabenProviderDefaultsTests(unittest.TestCase):
    def test_every_public_tracker_provider_has_scoped_knaben(self):
        # Knaben searches every public-tracker provider's categories On by
        # default; Auto (ask only when the On engines come back empty) and Off
        # stay available.
        cases = (
            (MovieProvider(), (2_000_000, 3_000_000), "on"),
            (GameProvider(), (4_000_000, 7_000_000), "on"),
            (SoftwareProvider(), (4_002_000, 4_003_000, 4_004_000), "on"),
            (MobileProvider(), (8_001_000,), "on"),
            (AnimeProvider(), (6_000_000,), "on"),
            (MangaProvider(), (6_006_000, 9_002_000), "on"),
            (BookProvider(), (9_000_000,), "on"),
        )

        for provider, categories, mode in cases:
            with self.subTest(provider=provider.slug):
                engine = next(e for e in provider.engines if e.name == "Knaben")
                self.assertEqual(engine.mode, mode)
                self.assertEqual(engine.available_modes, ("on", "auto", "off"))
                self.assertEqual(provider.knaben_categories, categories)

    def test_noisy_legacy_engines_are_manual_off_options(self):
        cases = (
            (MovieProvider(), {"SolidTorrents", "YTS"}),
            (GameProvider(), {"SolidTorrents"}),
            (SoftwareProvider(), {"SolidTorrents"}),
            (MobileProvider(), {"SolidTorrents", "F-Droid"}),
            (AnimeProvider(), {"SolidTorrents"}),
            (BookProvider(), {"SolidTorrents"}),
        )

        for provider, engine_names in cases:
            with self.subTest(provider=provider.slug):
                modes = {e.name: e.mode for e in provider.engines}
                self.assertTrue(all(modes[name] == "off" for name in engine_names))


class SavedAutoBecomesOnTests(unittest.TestCase):
    """Saved choices from before Knaben was On by default held its old Auto: it turns On once."""

    def saved(self, knaben_mode, **settings):
        isolation.isolate_store(self, data={
            "settings": settings,
            "providers": {"movies": {"engine_modes": {"Apibay": "on", "Knaben": knaben_mode, "Nyaa": "off"},
                                     "engines": {"Apibay": True, "Knaben": False, "Nyaa": False},
                                     "explicitly_disabled_engines": ["Nyaa"], "active_presets": []}}})

    def modes(self):
        provider = MovieProvider()
        state.load_state([provider])
        return {engine.name: engine.mode for engine in provider.engines}

    def test_a_saved_auto_turns_on_and_the_rest_stays(self):
        self.saved("auto")
        modes = self.modes()
        self.assertEqual((modes["Knaben"], modes["Apibay"], modes["Nyaa"]), ("on", "on", "off"))
        store.flush()  # as the app does on the way out
        isolation.restart_store()
        self.assertEqual(store.read()["providers"]["movies"]["engine_modes"]["Knaben"], "on")  # saved, once

    def test_an_auto_saved_where_knaben_was_already_on_is_kept(self):
        isolation.isolate_store(self, data={"providers": {"mobile": {
            "engine_modes": {"Knaben": "auto", "Apibay": "on"}, "active_presets": []}}})
        provider = MobileProvider()
        state.load_state([provider])
        self.assertEqual(next(e for e in provider.engines if e.name == "Knaben").mode, "auto")

    def test_off_stays_off(self):
        self.saved("off")
        self.assertEqual(self.modes()["Knaben"], "off")

    def test_an_auto_chosen_after_the_change_is_kept(self):
        self.saved("auto", knaben_on_by_default=True)
        self.assertEqual(self.modes()["Knaben"], "auto")

    def test_choosing_auto_now_survives_a_restart(self):
        isolation.isolate_store(self)
        provider = MovieProvider()
        next(e for e in provider.engines if e.name == "Knaben").set_mode("auto")
        state.save_state([provider])
        isolation.restart_store()
        self.assertEqual(self.modes()["Knaben"], "auto")


if __name__ == "__main__":
    unittest.main()
