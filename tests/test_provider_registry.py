import unittest

from torrent_finder.main import _build_parser
from torrent_finder.providers import (
    PROVIDERS,
    creator_facet_choices,
    get_provider,
    get_provider_by_slug,
    provider_cli_choices,
)


class ProviderRegistryTests(unittest.TestCase):
    def test_every_provider_slug_and_alias_resolves_to_its_provider(self):
        choices = provider_cli_choices()

        self.assertEqual(len(choices), len(set(choices)))
        for provider in PROVIDERS:
            self.assertIn(provider.slug, choices)
            self.assertIs(get_provider(provider.slug), provider)
            self.assertIs(get_provider_by_slug(provider.slug), provider)
            for alias in provider.cli_aliases:
                self.assertIn(alias, choices)
                self.assertIs(get_provider(alias), provider)
                self.assertIsNone(get_provider_by_slug(alias))

    def test_legacy_singular_aliases_remain_supported(self):
        self.assertEqual(get_provider("movie").slug, "movies")
        self.assertEqual(get_provider("game").slug, "games")

    def test_creator_choices_are_the_unique_union_of_provider_facets(self):
        expected = tuple(dict.fromkeys(
            facet.key
            for provider in PROVIDERS
            for facet in provider.creator_facets
        ))

        self.assertEqual(creator_facet_choices(), expected)


class ParserRegistryTests(unittest.TestCase):
    @staticmethod
    def _action_for(parser, option):
        return next(action for action in parser._actions if option in action.option_strings)

    def test_cli_choices_come_from_the_provider_registry(self):
        parser = _build_parser()

        self.assertEqual(
            tuple(self._action_for(parser, "--type").choices),
            provider_cli_choices(),
        )
        self.assertEqual(
            tuple(self._action_for(parser, "--by").choices),
            creator_facet_choices(),
        )

    def test_parser_accepts_legacy_aliases_and_canonical_slugs(self):
        parser = _build_parser()

        self.assertEqual(parser.parse_args(["-t", "movie"]).type, "movie")
        self.assertEqual(parser.parse_args(["-t", "movies"]).type, "movies")
        self.assertEqual(parser.parse_args(["-t", "game"]).type, "game")
        self.assertEqual(parser.parse_args(["-t", "games"]).type, "games")


if __name__ == "__main__":
    unittest.main()
