import unittest
import warnings

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from torrent_finder.providers.movie_provider import MovieProvider


class MovieProviderDefaultsTests(unittest.TestCase):
    def test_only_apibay_and_nyaa_are_enabled_by_default(self):
        provider = MovieProvider()

        enabled = {engine.name for engine in provider.engines if engine.enabled}
        self.assertEqual(enabled, {"Apibay", "Nyaa"})


if __name__ == "__main__":
    unittest.main()
