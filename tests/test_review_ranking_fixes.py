"""Ranking fixes from the 2026-10-04 final review, checked on real audit names."""

import unittest
from unittest.mock import patch

import isolation  # noqa: F401  (keeps the user's settings out of reach)
from torrent_finder.language_tags import has_brazilian_audio, is_raw_release
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.book_provider import BookProvider
from torrent_finder.providers.mobile_provider import MobileProvider
from torrent_finder.providers.software_provider import SoftwareProvider
from torrent_finder.result_view import (book_title_score, digit_spelling, game_title_query, matches_name,
                                        movie_title_score, release_tag_hits, title_score)
from torrent_finder.search_result import SearchResult


def row(name):
    return SearchResult(name=name, info_hash="a" * 40, source="Knaben")


class TitleNumberTests(unittest.TestCase):
    def test_numbers_in_the_searched_title_are_title_words(self):
        self.assertEqual(title_score("Cyberpunk 2077 v2.1 + All DLCs", "Cyberpunk 2077"), 3)
        self.assertEqual(book_title_score("George Orwell - 1984 [PDF]", "1984"), 3)
        self.assertEqual(book_title_score("Metro 2033 - Dmitry Glukhovsky.epub", "Metro 2033"), 3)

    def test_a_sequel_number_is_not_a_release_year(self):
        self.assertEqual(movie_title_score("Blade Runner 2049 (2017) 1080p", "Blade Runner"), 2)
        self.assertEqual(movie_title_score("Blade Runner (1982) Final Cut 1080p", "Blade Runner"), 3)
        self.assertEqual(movie_title_score("Wonder Woman 1984 (2020) 2160p", "Wonder Woman"), 2)
        self.assertEqual(movie_title_score("Friends 1994-2004 Complete", "Friends"), 3)  # a range is the year
        self.assertEqual(movie_title_score("1917 (2019) 1080p", "1917"), 3)

    def test_each_title_of_a_translated_listing_counts(self):
        name = ("Матрица / The Matrix [1999, США, фантастика, боевик, WEB-DL 2160p] [Hybrid] Dub + Original (Eng) "
                "+ Sub (Rus, Eng)")
        self.assertEqual(movie_title_score(name, "The Matrix"), 3)
        self.assertEqual(movie_title_score("Матрица: Революция / The Matrix: Revolutions [2003, США]", "The Matrix"), 2)

    def test_release_tags_typed_after_a_title_are_not_title_words(self):
        self.assertEqual(AnimeProvider().title_relevance(row("[SubsPlease] Saki - 01 (720p)"), "Saki 720p"), 3)

    def test_tag_spellings_match(self):
        for tag, name in (("ptbr", "Movie PT-BR"), ("h264", "Movie H.264"), ("bluray", "Movie Blu-Ray"),
                          ("web-dl", "Movie WEBDL")):
            with self.subTest(tag=tag):
                self.assertEqual(release_tag_hits(name, f"Movie {tag}"), 1)

    def test_exact_title_mode_keeps_numbered_titles(self):
        self.assertTrue(matches_name("Cyberpunk 2077 v2.1", "Cyberpunk 2077", mode="title"))


class BookAuthorTests(unittest.TestCase):
    def test_either_name_order_and_suffixes_match(self):
        self.assertEqual(book_title_score("Don Quixote — Cervantes, Miguel de [epub, English]", "Don Quixote",
                                          ("Miguel de Cervantes Saavedra",), "Cervantes, Miguel de"), 4)
        self.assertEqual(book_title_score("A Canticle for Leibowitz — Miller, Walter M. [epub]",
                                          "A Canticle for Leibowitz", ("Walter M. Miller Jr.",), "Miller, Walter M."), 4)
        # A torrent name has no author field: the surname itself must not be "Jr.".
        self.assertEqual(book_title_score("A Canticle for Leibowitz - Walter M. Miller (1959) epub",
                                          "A Canticle for Leibowitz", ("Walter M. Miller Jr.",)), 4)

    def test_author_lookup_ignores_format_words(self):
        with patch("torrent_finder.providers.book_provider.openlibrary.dominant_author", return_value=()) as lookup:
            BookProvider().lookup_authors("Pride and Prejudice epub")
        lookup.assert_called_once_with("Pride and Prejudice")


class LanguageTagTests(unittest.TestCase):
    def test_kanji_only_raws_and_japanese_tags(self):
        self.assertTrue(is_raw_release("咲 -Saki- 第01-27巻 [Saki vol 01-27]"))
        self.assertTrue(is_raw_release("One Piece 1194 [JP]"))
        self.assertTrue(is_raw_release("Berserk Vol. 1/39 (Jap, 1989)"))
        self.assertFalse(is_raw_release("海贼王 第1卷 (Chinese)"))  # the Chinese volume character
        self.assertFalse(is_raw_release("One Piece v105 (Digital)"))

    def test_brazilian_audio_after_another_audio_language(self):
        self.assertTrue(has_brazilian_audio("[Anitsu] Sousou no Frieren S01 [BD 1080p] [DUAL JAP PT-BR] [SUB PT-BR ENG]"))
        self.assertFalse(has_brazilian_audio("Sousou no Frieren S01 [JAP] [SUB PT-BR ENG]"))


class ProductTests(unittest.TestCase):
    def test_desktop_programs_about_mobile_platforms_stay(self):
        names = ["Android Studio Hedgehog 2023.1.1 Windows x64", "BlueStacks 5 Android Emulator for Windows",
                 "Xcode 15 (iOS SDK) for macOS", "WhatsApp for Android 2.24 APK"]
        kept, _ = SoftwareProvider().filter_with_reasons([row(n) for n in names])
        self.assertEqual([r.name for r in kept], names[:3])

    def test_mobile_listings_naming_android_too_stay(self):
        names = ["Minecraft PE 1.20 [Android + iOS]", "Launcher iOS 17 v6.1 Premium APK", "Minecraft iOS IPA"]
        kept, _ = MobileProvider().filter_with_reasons([row(n) for n in names])
        self.assertEqual([r.name for r in kept], names[:2])

    def test_game_platform_words_only_at_the_end(self):
        self.assertEqual(game_title_query("PC Building Simulator"), "PC Building Simulator")
        self.assertEqual(game_title_query("Mac and Cheese Simulator"), "Mac and Cheese Simulator")
        self.assertEqual(game_title_query("Elden Ring PC repack"), "Elden Ring")

    def test_modifier_letter_apostrophe(self):
        self.assertTrue(matches_name("Baldurʼs Gate 3", "Baldurs Gate 3"))


class DigitSpellingTests(unittest.TestCase):
    def test_years_thousands_and_brackets(self):
        self.assertEqual(digit_spelling("Nineteen Eighty-Four"), "1984")
        self.assertIsNone(digit_spelling("One Thousand and One Nights"))
        self.assertEqual(digit_spelling("Toy Story (Two)"), "Toy Story (2)")


if __name__ == "__main__":
    unittest.main()
