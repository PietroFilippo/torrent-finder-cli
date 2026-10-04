"""Titles are found under the spelling each source uses (user report, 2026-10-04).

"Mahjong Hishoden: Naki no Ryuu" found nothing: Madokami's search fails on the
colon and knows "Hishoden"; Nyaa and Knaben list "Hishouden"; AniList's romaji
is "Mahjong Hishou-den Naki no Ryuu" and its synonym "Naki no Ryuu" is the
short name every source finds. Fixtures copy those live answers.
"""

import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import isolation  # noqa: F401  (keeps the user's settings out of reach)
from torrent_finder import madokami
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.madokami_provider import MadokamiProvider
from torrent_finder.providers.manga_provider import MangaProvider
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.resolvers import titles
from torrent_finder.result_view import (reduced_title, same_spelling, same_title, short_vowel_spelling,
                                        title_starts_with)
from torrent_finder.search_result import SearchResult
from torrent_finder.search_session import SearchSession

NAKI = {"title": {"romaji": "Mahjong Hishou-den Naki no Ryuu", "english": "Mahjong Hishoden Naki no Ryuu",
                  "native": "麻雀飛翔伝 哭きの竜"}, "synonyms": ["Weeping Dragon", "Naki no Ryuu", "Ryuu"]}
TATE = {"title": {"romaji": "Tate no Yuusha no Nariagari", "english": "The Rising of the Shield Hero"}, "synonyms": []}
GITS_SPINOFF = {"title": {"romaji": "Koukaku Kidoutai: Stand Alone Complex - Solid State Society 3D",
                          "english": None}, "synonyms": []}


def page(*media):
    return {"Page": {"pageInfo": {"hasNextPage": False}, "media": list(media)}}


class SpellingHelperTests(unittest.TestCase):
    def test_long_vowels_written_short(self):
        for typed, short in (("Shingeki no Kyoujin", "Shingeki no Kyojin"), ("Mahjong Hishouden", "Mahjong Hishoden"),
                             ("Shoujo Shuumatsu Ryokou", "Shojo Shumatsu Ryoko"), ("Toukyou Ghoul", "Tokyo Ghoul"),
                             ("Ookami to Koushinryou", "Okami to Koshinryo"),
                             ("Haunted House", None), ("Are you there", None), ("Taboo Tattoo", None)):
            with self.subTest(typed=typed):
                self.assertEqual(short_vowel_spelling(typed), short)

    def test_names_compare_across_spellings_but_searches_do_not(self):
        self.assertTrue(same_title("Mahjong Hishouden: Naki no Ryuu", "Mahjong Hishou-den Naki no Ryuu"))
        self.assertTrue(same_title("Tate no Yusha no Nariagari", "Tate no Yuusha no Nariagari"))
        self.assertFalse(same_spelling("Mahjong Hishouden Naki no Ryuu", "Mahjong Hishoden: Naki no Ryuu"))
        self.assertTrue(same_spelling("Mahjong Hishoden Naki no Ryuu", "Mahjong Hishoden: Naki no Ryuu"))

    def test_a_typed_prefix_names_the_work_unless_it_is_a_franchise_name(self):
        self.assertTrue(title_starts_with("Mahjong Hishoden Naki no Ryuu", "Mahjong Hishoden"))
        self.assertFalse(title_starts_with("Koukaku Kidoutai: Stand Alone Complex", "Kokaku Kidotai"))
        self.assertFalse(title_starts_with("Mahjong Club", "Mahjong Hishoden"))
        self.assertFalse(title_starts_with("Berserk of Gluttony", "Berserk"))  # one word names too much

    def test_reduced_titles_keep_words_that_cannot_hide_a_long_vowel(self):
        self.assertEqual(reduced_title("Tate no Yusha no Nariagari"), "Tate Nariagari")
        self.assertEqual(reduced_title("Shumatsu no Valkyrie"), "Valkyrie")
        self.assertEqual(reduced_title("Kaguya-sama wa Kokurasetai"), "Kaguya-sama")  # particles go too
        self.assertIsNone(reduced_title("Shojo Shumatsu Ryoko"))
        self.assertIsNone(reduced_title("Koi wa Ame"))  # "Ame" alone is too short to search


class KnownAliasTests(unittest.TestCase):
    def aliases(self, query, answers):
        searched = []

        def post(_query, variables):
            searched.append(variables["search"])
            return page(*answers.get(variables["search"], ()))
        with patch.object(titles.anilist, "_post", side_effect=post):
            found = titles.known_aliases("manga", query)
        return found, searched

    def test_the_release_spelling_and_short_name_of_the_work(self):
        found, _ = self.aliases("Mahjong Hishoden: Naki no Ryuu", {"Mahjong Hishoden: Naki no Ryuu": [NAKI]})
        self.assertEqual(found, ("Mahjong Hishouden Naki no Ryuu", "Naki no Ryuu"))

    def test_a_typed_series_prefix_finds_the_work(self):
        found, _ = self.aliases("Mahjong Hishoden", {"Mahjong Hishoden": [NAKI]})
        self.assertEqual(found, ("Mahjong Hishouden Naki no Ryuu", "Mahjong Hishoden Naki no Ryuu", "Naki no Ryuu"))

    def test_catalog_spelling_is_reached_through_the_unambiguous_words(self):
        found, searched = self.aliases("Tate no Yusha no Nariagari", {"Tate Nariagari": [TATE]})
        self.assertEqual(searched, ["Tate no Yusha no Nariagari", "Tate Nariagari"])
        self.assertEqual(found, ("Tate no Yuusha no Nariagari", "The Rising of the Shield Hero"))

    def test_only_the_top_match_s_own_titles_may_start_with_the_query(self):
        club = {"title": {"romaji": "Mahjong Club", "english": None}, "synonyms": []}
        self.assertEqual(self.aliases("Mahjong Hishoden", {"Mahjong Hishoden": [club, NAKI]})[0], ())
        listed = {"title": {"romaji": "Naki no Ryuu Gaiden", "english": None}, "synonyms": ["Mahjong Hishoden Gaiden"]}
        self.assertEqual(self.aliases("Mahjong Hishoden", {"Mahjong Hishoden": [listed]})[0], ())

    def test_each_name_is_searched_once(self):
        titan = {"title": {"romaji": "Shingeki no Kyojin", "english": "Attack on Titan"}, "synonyms": ["Shingeki no Kyojin"]}
        found, _ = self.aliases("Shingeki no Kyoujin", {"Shingeki no Kyoujin": [titan]})
        self.assertEqual(found, ("Shingeki no Kyojin", "Attack on Titan"))

    def test_a_franchise_name_is_not_a_spin_off(self):
        self.assertEqual(self.aliases("Kokaku Kidotai", {"Kokaku Kidotai": [GITS_SPINOFF]})[0], ())

    def test_honorific_hyphens_stay(self):
        kaguya = {"title": {"romaji": "Kaguya-sama wa Kokurasetai: Tensai-tachi no Renai Zunousen",
                            "english": "Kaguya-sama: Love is War"}, "synonyms": []}
        found, _ = self.aliases("Kaguya-sama: Love is War", {"Kaguya-sama: Love is War": [kaguya]})
        self.assertEqual(found, ("Kaguya-sama wa Kokurasetai: Tensai-tachi no Renai Zunousen",))


class MadokamiPunctuationTests(unittest.TestCase):
    def test_a_search_with_punctuation_is_retried_without_it(self):
        empty = Mock(status_code=200, text="<table></table>")
        hit = Mock(status_code=200, text='<td><a href="/Manga/N/NA/NAKI/Naki%20no%20Ryuu">x</a></td>')
        session = Mock()
        session.get.side_effect = [empty, hit]
        with patch.object(madokami, "_get_session", return_value=session):
            rows = madokami.search("Mahjong Hishoden: Naki no Ryuu")
        self.assertEqual([r.name for r in rows], ["Naki no Ryuu [series folder]"])
        self.assertEqual([c.kwargs["params"]["q"] for c in session.get.call_args_list],
                         ["Mahjong Hishoden: Naki no Ryuu", "Mahjong Hishoden Naki no Ryuu"])


def row(name, info_hash, source="Nyaa"):
    return SearchResult(name=name, info_hash=info_hash, seeders=1, source=source)


class CombinedNameTests(unittest.TestCase):
    """The user's combined search: Movies & Series, Anime, Manga, Madokami."""

    def run_search(self, query, answers, aliases):
        calls = []

        def engine(label):
            def search(_self, q, *_rest):
                calls.append((label, q))
                return list(answers.get((label, q), []))
            return search

        with ExitStack() as stack:
            for cls, method, label in ((MovieProvider, "_search_apibay", "movies"), (MovieProvider, "_search_knaben", "movies"),
                                       (MovieProvider, "_search_nyaa", "movies"), (AnimeProvider, "_search_nyaa", "anime"),
                                       (AnimeProvider, "_search_knaben", "anime"), (MangaProvider, "_search_nyaa", "manga"),
                                       (MangaProvider, "_search_apibay", "manga"), (MangaProvider, "_search_knaben", "manga")):
                stack.enter_context(patch.object(cls, method, engine(label)))
            stack.enter_context(patch.object(madokami, "search", lambda q: calls.append(("madokami", q))
                                             or list(answers.get(("madokami", q), []))))
            stack.enter_context(patch.object(titles, "known_aliases", lambda catalog, q, limit=3: aliases.get((catalog, q), ())))
            for cls in (AnimeProvider, MangaProvider, MadokamiProvider):
                stack.enter_context(patch.object(cls, "looks_up_aliases", True))
            providers = [MovieProvider(), AnimeProvider(), MangaProvider(), MadokamiProvider()]
            return SearchSession(providers, [query], combined=True).run(), calls

    def test_catalog_names_serve_every_provider_and_releases_go_to_the_specific_one(self):
        orphan = "[Orphan] Mahjong Hishouden Naki no Ryuu (480p)"
        answers = {("anime", "Mahjong Hishouden Naki no Ryuu"): [row(orphan, "a" * 40)],
                   ("movies", "Mahjong Hishouden Naki no Ryuu"): [row(orphan, "a" * 40, "Knaben")],
                   ("madokami", "Naki no Ryuu"): [SearchResult(name="Naki no Ryuu [series folder]", info_hash="madokami:/x",
                                                               source="Madokami", handle={"mdk_path": "/Manga/N/NA/NAKI/Naki no Ryuu"})]}
        aliases = {("manga", "Mahjong Hishoden: Naki no Ryuu"): ("Mahjong Hishouden Naki no Ryuu", "Naki no Ryuu")}
        results, calls = self.run_search("Mahjong Hishoden: Naki no Ryuu", answers, aliases)
        self.assertIn(("movies", "Naki no Ryuu"), calls)  # Movies & Series has no catalog of its own
        by_name = {r.name: r for r in results}
        self.assertEqual(by_name[orphan]["provider_label"], "Anime")
        self.assertEqual(sorted(by_name[orphan]["matched_providers"]), ["anime", "movies"])
        self.assertIn("Naki no Ryuu [series folder]", by_name)

    def test_long_vowels_are_retried_short_for_every_provider(self):
        answers = {("madokami", "Mahjong Hishoden"): [SearchResult(name="Naki no Ryuu [series folder]",
                                                                   info_hash="madokami:/x", source="Madokami",
                                                                   handle={"mdk_path": "/Manga/N/NA/NAKI/Naki no Ryuu"})]}
        results, calls = self.run_search("Mahjong Hishouden", answers, {})
        self.assertIn(("madokami", "Mahjong Hishoden"), calls)
        self.assertIn(("anime", "Mahjong Hishoden"), calls)
        self.assertEqual([r.name for r in results], ["Naki no Ryuu [series folder]"])
        self.assertIn("Nothing matched “Mahjong Hishouden”, so “Mahjong Hishoden” was searched too.", results.notices)


if __name__ == "__main__":
    unittest.main()
