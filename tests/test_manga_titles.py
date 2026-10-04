"""General Manga finds a work under another name and honours a typed language (P09).

Live October 2026 checks behind the fixtures: "Yokohama Shopping Log" found
nothing on Nyaa while AniList lists it as a synonym of "Yokohama Kaidashi
Kikou"; Nyaa's Non-English manga for Berserk were Italian, Spanish, French and
Arabic, with nothing tagged Portuguese.
"""

import unittest
from contextlib import ExitStack
from unittest.mock import patch

import isolation  # noqa: F401  (keeps the user's settings out of reach)
from torrent_finder.language_tags import is_raw_release, manga_language_tag
from torrent_finder.providers.manga_provider import MangaProvider, typed_language
from torrent_finder.resolvers import titles
from torrent_finder.search_result import SearchResult
from torrent_finder.search_session import search_many


def row(name, seeders=1, n=[0]):
    n[0] += 1
    return SearchResult(name=name, info_hash=f"{n[0]:040x}", seeders=seeders, source="Nyaa")


class MangaCase(unittest.TestCase):
    """Fake sources: {engine: {query: rows}}; anything else returns nothing."""

    def search(self, query, sources, aliases=None, fail=()):
        calls = []

        def engine(name):
            def search(_self, q, *category):
                key = name if not category else {"3_2": "Non-English", "3_3": "Raw"}[category[0]]
                calls.append((key, q))
                if key in fail:
                    raise RuntimeError("source down")
                return list(sources.get(key, {}).get(q, []))
            return search

        lookups = []

        def lookup_aliases(_self, q):
            lookups.append(q)
            if isinstance(aliases, Exception):
                raise aliases
            return (aliases or {}).get(q, ())

        with ExitStack() as stack:
            for method, name in (("_search_nyaa", "EN"), ("_search_nyaa_in", None),
                                 ("_search_apibay", "Apibay"), ("_search_knaben", "Knaben")):
                stack.enter_context(patch.object(MangaProvider, method, engine(name)))
            stack.enter_context(patch.object(MangaProvider, "lookup_aliases", lookup_aliases))
            stack.enter_context(patch.object(MangaProvider, "looks_up_aliases", True))
            results = search_many(MangaProvider(), [query])
        self.calls, self.lookups = calls, lookups
        return results


class AliasTests(MangaCase):
    YKK = {"EN": {"Yokohama Kaidashi Kikou": [row("Yokohama Kaidashi Kikou - Deluxe Edition (Digital) (1r0n)", 68)]},
           "Apibay": {"Yokohama Shopping Log": [row("Yokohama Kaidashi Kikou [Manga] - Hitoshi Ashinano")]}}

    def test_a_title_that_matches_nothing_is_searched_under_its_catalog_name(self):
        results = self.search("Yokohama Shopping Log", self.YKK,
                              aliases={"Yokohama Shopping Log": ("Yokohama Kaidashi Kikou",)})
        self.assertEqual(self.lookups, ["Yokohama Shopping Log"])
        self.assertEqual(results[0].name, "Yokohama Kaidashi Kikou - Deluxe Edition (Digital) (1r0n)")
        self.assertEqual(results[0]["from_work"], "Yokohama Kaidashi Kikou")
        self.assertIn(("EN", "Yokohama Kaidashi Kikou"), self.calls)
        self.assertIn("Nothing matched “Yokohama Shopping Log”, so its catalog title was searched too: "
                      "“Yokohama Kaidashi Kikou”.", results.notices)

    def test_no_lookup_when_a_row_matches_the_title(self):
        results = self.search("Berserk", {"EN": {"Berserk": [row("Berserk v01-40 (Digital)")]}},
                              aliases={"Berserk": ("Should not be used",)})
        self.assertEqual(self.lookups, [])
        self.assertEqual(len(results), 1)

    def test_no_lookup_when_every_source_failed(self):
        self.search("Yokohama Shopping Log", {}, fail=("EN", "Apibay", "Knaben"),
                    aliases={"Yokohama Shopping Log": ("Yokohama Kaidashi Kikou",)})
        self.assertEqual(self.lookups, [])

    def test_a_failed_or_empty_lookup_ends_the_search_quietly(self):
        for aliases in (RuntimeError("AniList down"), {}):
            with self.subTest(aliases=aliases):
                results = self.search("Twenty First Century Boys", {}, aliases=aliases)
                self.assertEqual((list(results), self.lookups), ([], ["Twenty First Century Boys"]))
                self.assertFalse(any("catalog title" in notice for notice in results.notices))


def anilist_page(*media):
    return {"Page": {"pageInfo": {"hasNextPage": False}, "media": list(media)}}


def media(romaji, english=None, native=None, synonyms=()):
    return {"id": 1, "title": {"romaji": romaji, "english": english, "native": native},
            "synonyms": list(synonyms)}


class KnownAliasTests(unittest.TestCase):
    def aliases(self, query, *nodes):
        with patch.object(titles.anilist, "_post", return_value=anilist_page(*nodes)):
            return titles.known_aliases("manga", query)

    def test_a_synonym_or_english_title_gives_the_other_titles(self):
        ykk = media("Yokohama Kaidashi Kikou", native="ヨコハマ買い出し紀行",
                    synonyms=("Yokohama Shopping Log", "YKK"))
        self.assertEqual(self.aliases("Yokohama Shopping Log", ykk), ("Yokohama Kaidashi Kikou",))
        aot = media("Shingeki no Kyojin", "Attack on Titan", "進撃の巨人")
        self.assertEqual(self.aliases("attack on titan", aot), ("Shingeki no Kyojin",))

    def test_only_an_exact_name_counts(self):
        self.assertEqual(self.aliases("Twenty First Century Boys", media("21st Century Boys")), ())
        self.assertEqual(self.aliases("Berserk", media("Berserk", native="ベルセルク"),
                                      media("Boushoku no Berserk", synonyms=("Berserk",))), ())

    def test_catalog_failure_means_no_aliases(self):
        with patch.object(titles.anilist, "_post", return_value=None):
            self.assertEqual(titles.known_aliases("manga", "Anything"), ())


class TypedLanguageTests(MangaCase):
    BERSERK = {"EN": {"Berserk": [row("Berserk v01-40 (2003-2019) (Digital) (danke-Empire)", 330)]},
               "Non-English": {"Berserk": [row("Berserk vols 01-37 [es] emangalia", 3),
                                           row("Berserk - Volume 1 (Português) PT-BR", 1)]}}

    def test_a_typed_language_searches_the_title_in_that_category_and_lists_tagged_rows_first(self):
        provider = MangaProvider()
        self.assertEqual(provider.engines[2].mode, "off")  # Nyaa (Non-English) saved Off
        results = self.search("Berserk português", self.BERSERK)
        self.assertIn(("Non-English", "Berserk"), self.calls)
        self.assertNotIn("Raw", {engine for engine, _ in self.calls})
        self.assertEqual(results[0].name, "Berserk - Volume 1 (Português) PT-BR")
        self.assertIn("1 result(s) carry a Portuguese tag and are listed first; the title alone was searched too.",
                      results.notices)
        self.assertEqual(self.lookups, [])  # Berserk rows match the title; no alias lookup

    def test_no_tagged_row_is_said_plainly(self):
        sources = {"EN": self.BERSERK["EN"], "Non-English": {"Berserk": [row("Berserk vols 01-37 [es] emangalia")]}}
        results = self.search("Berserk portugues", sources)
        self.assertEqual(len(results), 2)
        self.assertIn("No result carries a Portuguese tag; the title alone was searched too, so other releases "
                      "are shown.", results.notices)
        self.assertEqual(self.lookups, [])  # the rows match "Berserk"; the language is not part of the title

    def test_typed_language_only_at_the_end_and_after_a_title(self):
        self.assertEqual(typed_language("Berserk português"), ("Berserk", "Portuguese"))
        self.assertEqual(typed_language("One Piece raw"), ("One Piece", "Raw (Japanese)"))
        self.assertIsNone(typed_language("The Italian Job"))
        self.assertIsNone(typed_language("Raw"))
        self.assertEqual(MangaProvider().expand_queries("Berserk italiano"), ["Berserk italiano", "Berserk"])

    def test_language_tags(self):
        for language, name, tagged in (
            ("spanish", "Berserk vols 01-37 [es] emangalia", True),
            ("spanish", "Berserk - 377 Arabic.cbz", False),
            ("italian", "Berserk Maximum 01-03 (Planet Manga) [digital Yfe] (Italian)", True),
            ("italian", "[Manga ITA] Berserk Collection Vol.34", True),
            ("french", "Berserk VF (01-39) (Miura) [Digital]", True),
            ("portuguese", "Berserk - Volume 1 (Português) PT-BR", True),
            ("portuguese", "Berserk Pt. 2 (Digital)", False),
        ):
            with self.subTest(name=name):
                self.assertEqual(manga_language_tag(language)(name), tagged)
        self.assertTrue(is_raw_release("ヨコハマ買い出し紀行 第01-14巻"))
        self.assertTrue(is_raw_release("One Piece [RAW] v105"))
        self.assertFalse(is_raw_release("One Piece v105 (Digital)"))


if __name__ == "__main__":
    unittest.main()
