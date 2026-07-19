import unittest

from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.book_provider import BookProvider
from torrent_finder.providers.game_provider import GameProvider
from torrent_finder.providers.manga_provider import MangaProvider
from torrent_finder.providers.mobile_provider import MobileProvider
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.providers.software_provider import SoftwareProvider


class KnabenProviderDefaultsTests(unittest.TestCase):
    def test_every_public_tracker_provider_has_scoped_auto_knaben(self):
        cases = (
            (MovieProvider(), (2_000_000, 3_000_000)),
            (GameProvider(), (4_000_000, 7_000_000)),
            (SoftwareProvider(), (4_002_000, 4_003_000, 4_004_000)),
            (MobileProvider(), (8_001_000,)),
            (AnimeProvider(), (6_000_000,)),
            (MangaProvider(), (6_006_000, 9_002_000)),
            (BookProvider(), (9_000_000,)),
        )

        for provider, categories in cases:
            with self.subTest(provider=provider.slug):
                engine = next(e for e in provider.engines if e.name == "Knaben")
                self.assertEqual(engine.mode, "auto")
                self.assertEqual(provider.knaben_categories, categories)

    def test_noisy_legacy_engines_are_manual_off_options(self):
        cases = (
            (MovieProvider(), {"SolidTorrents", "YTS"}),
            (GameProvider(), {"SolidTorrents"}),
            (SoftwareProvider(), {"SolidTorrents"}),
            (MobileProvider(), {"SolidTorrents"}),
            (AnimeProvider(), {"SolidTorrents"}),
            (BookProvider(), {"SolidTorrents"}),
        )

        for provider, engine_names in cases:
            with self.subTest(provider=provider.slug):
                modes = {e.name: e.mode for e in provider.engines}
                self.assertTrue(all(modes[name] == "off" for name in engine_names))


if __name__ == "__main__":
    unittest.main()
