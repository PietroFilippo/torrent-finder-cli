import unittest

from torrent_finder.ui.tips import find_tips


class TipsCatalogTests(unittest.TestCase):
    def test_knaben_fallback_help_is_searchable(self):
        matches = find_tips("Knaben", category="Filters & Selection")
        texts = [tip.text for _category, tip in matches]

        self.assertTrue(any("starts on Auto" in text for text in texts))
        self.assertTrue(any("Knaben tracker" in text for text in texts))

    def test_engine_mode_semantics_are_searchable(self):
        matches = find_tips("Off is never contacted")

        self.assertTrue(matches)
        self.assertTrue(any("Auto runs only" in tip.text for _category, tip in matches))


if __name__ == "__main__":
    unittest.main()
