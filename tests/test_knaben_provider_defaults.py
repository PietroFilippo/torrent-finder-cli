import unittest

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.book_provider import BookProvider
from torrent_finder.providers.game_provider import GameProvider
from torrent_finder.providers.manga_provider import MangaProvider
from torrent_finder.providers.mobile_provider import MobileProvider
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.providers.software_provider import SoftwareProvider


class KnabenProviderDefaultsTests(unittest.TestCase):
    def test_every_public_tracker_provider_has_scoped_knaben(self):
        # Desktop searches Knaben alongside APIBay (the audit's APIBay found
        # rows for 8 of 32 programs in 5.4 s on average, Knaben 26 in 0.8 s),
        # and Mobile first with APIBay as its Auto fallback (APIBay found rows
        # for 1 of 32, all also in Knaben's); elsewhere Knaben is the Auto
        # fallback. Either can be switched.
        cases = (
            (MovieProvider(), (2_000_000, 3_000_000), "auto"),
            (GameProvider(), (4_000_000, 7_000_000), "auto"),
            (SoftwareProvider(), (4_002_000, 4_003_000, 4_004_000), "on"),
            (MobileProvider(), (8_001_000,), "on"),
            (AnimeProvider(), (6_000_000,), "auto"),
            (MangaProvider(), (6_006_000, 9_002_000), "auto"),
            (BookProvider(), (9_000_000,), "auto"),
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


if __name__ == "__main__":
    unittest.main()
