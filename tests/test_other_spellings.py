"""Titles that match nothing are retried with spelled-out numbers in digits, and
Madokami also retries under AniList's names.

Live October 2026 checks behind the fixtures: no catalog lists "Twenty First
Century Boys", but Nyaa has six "21st Century Boys" releases and twelve "Mob
Psycho 100" ones; Madokami found nothing for "Yokohama Shopping Log" while its
folder is "Yokohama Kaidashi Kikou".
"""

import unittest
from contextlib import ExitStack
from unittest.mock import patch

import isolation  # noqa: F401  (keeps the user's settings out of reach)
from torrent_finder import madokami
from torrent_finder.providers.combined_provider import CombinedProvider
from torrent_finder.providers.madokami_provider import MadokamiProvider
from torrent_finder.providers.manga_provider import MangaProvider
from torrent_finder.providers.software_provider import SoftwareProvider
from torrent_finder.resolvers import titles
from torrent_finder.result_view import digit_spelling
from torrent_finder.search_result import SearchResult
from torrent_finder.search_session import search_many


def row(name, source="Nyaa", n=[0]):
    n[0] += 1
    return SearchResult(name=name, info_hash=f"{n[0]:040x}", seeders=1, source=source)


def folder(path):
    return SearchResult(name=madokami.display_name(path), info_hash=f"madokami:{path}", source="Madokami",
                        handle={"mdk_path": path})


YKK = "/Manga/Y/YO/YOKO/Yokohama%20Kaidashi%20Kikou"


class DigitSpellingTests(unittest.TestCase):
    def test_spelled_out_numbers_become_digits(self):
        for typed, digits in (
            ("Twenty First Century Boys", "21st Century Boys"),
            ("Twentieth Century Boys", "20th Century Boys"),
            ("Mob Psycho Hundred", "Mob Psycho 100"),
            ("One Hundred and One Dalmatians", "101 Dalmatians"),
            ("Catch-Twenty-Two", "Catch-22"),
            ("Ocean's Eleven", "Ocean's 11"),
            ("Twenty Second Century", "22nd Century"),
            ("Seven Samurai: Remastered", "7 Samurai: Remastered"),
            ("Twenty Thousand Leagues Under the Sea", None),  # 20,000 is not "20"
            ("Spider-Man", None),
            ("21st Century Boys", None),
        ):
            with self.subTest(typed=typed):
                self.assertEqual(digit_spelling(typed), digits)


class Sources:
    """Fake engine methods answering {(engine, query): rows}; records calls."""

    def __init__(self, answers):
        self.answers, self.calls, self.lookups = answers, [], []

    def engine(self, name):
        def search(_self, query, *_category):
            self.calls.append((name, query))
            return list(self.answers.get((name, query), []))
        return search

    def patches(self, stack, aliases=None):
        for cls, method, name in ((MangaProvider, "_search_nyaa", "Nyaa"), (MangaProvider, "_search_nyaa_in", "Nyaa"),
                                  (MangaProvider, "_search_apibay", "Apibay"),
                                  (MangaProvider, "_search_knaben", "Knaben"),
                                  (SoftwareProvider, "_search_apibay", "Apibay"),
                                  (SoftwareProvider, "_search_knaben", "Knaben")):
            stack.enter_context(patch.object(cls, method, self.engine(name)))
        stack.enter_context(patch.object(madokami, "search", lambda q: self.calls.append(("Madokami", q))
                                         or list(self.answers.get(("Madokami", q), []))))

        def known_aliases(catalog, query, limit=2):
            self.lookups.append((catalog, query))
            return (aliases or {}).get(query, ())
        stack.enter_context(patch.object(titles, "known_aliases", known_aliases))
        for cls in (MangaProvider, MadokamiProvider):
            stack.enter_context(patch.object(cls, "looks_up_aliases", True))


class OtherSpellingSearchTests(unittest.TestCase):
    def search(self, provider, query, answers, aliases=None):
        sources = Sources(answers)
        with ExitStack() as stack:
            sources.patches(stack, aliases)
            results = search_many(provider, [query])
        return results, sources

    def test_a_title_with_spelled_out_numbers_is_retried_in_digits(self):
        answers = {("Nyaa", "21st Century Boys"): [row("[0v3r] 21st Century Boys v01-02 (complete)")]}
        results, sources = self.search(MangaProvider(), "Twenty First Century Boys", answers)
        self.assertEqual([r.name for r in results], ["[0v3r] 21st Century Boys v01-02 (complete)"])
        self.assertIn("Nothing matched “Twenty First Century Boys”, so “21st Century Boys” was searched too.",
                      results.notices)
        self.assertEqual(sources.lookups, [("manga", "Twenty First Century Boys")])  # one round only

    def test_no_retry_when_rows_already_match_the_digits(self):
        answers = {("Nyaa", "Mob Psycho Hundred"): [row("Mob Psycho 100 v01-13 (Digital) (LuCaZ)")]}
        results, sources = self.search(MangaProvider(), "Mob Psycho Hundred", answers)
        self.assertEqual(len(results), 1)
        self.assertNotIn(("Nyaa", "Mob Psycho 100"), sources.calls)
        self.assertEqual(sources.lookups, [])

    def test_every_provider_gets_the_digit_retry(self):
        answers = {("Knaben", "Windows 11"): [row("Windows 11 Pro 24H2 x64", "Knaben")]}
        results, sources = self.search(SoftwareProvider(), "Windows Eleven", answers)
        self.assertEqual([r.name for r in results], ["Windows 11 Pro 24H2 x64"])
        self.assertEqual(sources.lookups, [])  # Desktop has no title catalog

    def test_madokami_retries_under_the_catalog_title(self):
        answers = {("Madokami", "Yokohama Kaidashi Kikou"): [folder(YKK)]}
        results, sources = self.search(MadokamiProvider(), "Yokohama Shopping Log", answers,
                                       aliases={"Yokohama Shopping Log": ("Yokohama Kaidashi Kikou",)})
        self.assertEqual([r.name for r in results], ["Yokohama Kaidashi Kikou [series folder]"])
        self.assertEqual(sources.calls, [("Madokami", "Yokohama Shopping Log"), ("Madokami", "Yokohama Kaidashi Kikou")])

    def test_combined_providers_share_one_catalog_lookup(self):
        answers = {("Madokami", "Yokohama Kaidashi Kikou"): [folder(YKK)],
                   ("Nyaa", "Yokohama Kaidashi Kikou"): [row("Yokohama Kaidashi Kikou - Deluxe Edition (Digital)")]}
        combined = CombinedProvider([MangaProvider(), MadokamiProvider()])
        combined.restore({})
        results, sources = self.search(combined, "Yokohama Shopping Log", answers,
                                       aliases={"Yokohama Shopping Log": ("Yokohama Kaidashi Kikou",)})
        self.assertEqual(sources.lookups, [("manga", "Yokohama Shopping Log")])
        self.assertIn(("Madokami", "Yokohama Kaidashi Kikou"), sources.calls)
        self.assertIn(("Nyaa", "Yokohama Kaidashi Kikou"), sources.calls)
        self.assertEqual({r.source for r in results}, {"Madokami", "Nyaa"})
        self.assertEqual(sum("catalog title" in notice for notice in results.notices), 1)


if __name__ == "__main__":
    unittest.main()
