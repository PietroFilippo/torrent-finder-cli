import unittest
from unittest.mock import patch

import isolation  # noqa: F401  # redirected settings and the shared test baseline
import torrent_finder


class _Answered:
    """A finished ``git describe`` thread."""

    def join(self, _timeout=None):
        pass


class CheckoutVersionTests(unittest.TestCase):
    def version(self, described):
        with patch.object(torrent_finder, "_describing", _Answered()), \
             patch.object(torrent_finder, "_described", [described] if described is not None else []):
            return torrent_finder._checkout_version()

    def test_a_tagged_commit_is_the_tag(self):
        self.assertEqual(self.version("v0.9.0-0-gcf8e8e0"), "0.9.0")

    def test_commits_after_a_tag_are_the_next_patch_dev_build(self):
        # As setuptools-scm names them, so a build and a checkout agree.
        self.assertEqual(self.version("v0.9.0-5-gcf8e8e0"), "0.9.1.dev5")

    def test_no_answer_falls_back_to_the_built_version(self):
        self.assertIsNone(self.version(None))
        self.assertIsNone(self.version("fatal: No names found"))

    def test_outside_a_checkout_git_is_not_asked(self):
        with patch.object(torrent_finder, "_describing", None):
            self.assertIsNone(torrent_finder._checkout_version())

    def test_the_version_is_a_plain_string(self):
        self.assertIsInstance(torrent_finder.__version__, str)
        self.assertTrue(torrent_finder.__version__)


if __name__ == "__main__":
    unittest.main()
