import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from rich.text import Text

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from torrent_finder.updates import _is_newer, notice_line


class UpdateNoticeTests(unittest.TestCase):
    def test_no_info_gives_empty_line(self):
        self.assertEqual(notice_line(None), "")

    def test_notice_survives_a_dim_base_style(self):
        # The provider-menu footer renders with a dim base style; the notice
        # must carry "not dim" so it stays bright there.
        from torrent_finder.ui import theme
        line = notice_line({"kind": "pip", "current": "0.1.0", "latest": "9.9.9"})
        self.assertIn("[banner]", line)
        self.assertIn("not dim", theme.STYLES["banner"])
        self.assertIn("not dim", theme.STYLES["banner.action"])
        self.assertIn("on yellow", theme.STYLES["banner"])  # the default theme's warn colour
        self.assertIn("9.9.9", line)
        Text.from_markup(line, style="dim")  # must parse as valid markup

    def test_each_kind_names_its_update_path(self):
        git = notice_line({"kind": "git", "behind": 2})
        self.assertIn("git pull", git)
        self.assertIn("2 commits behind", git)

        binary = notice_line({"kind": "binary", "current": "0.1.0", "latest": "9.9.9"})
        self.assertIn("releases", binary)


class IsNewerWithoutPackagingTests(unittest.TestCase):
    """Installs without the ``packaging`` dist must still compare sanely.

    The old fallback was ``latest != current``, which showed a stale cached
    "update to 0.3.0" banner right after updating to 0.3.1.
    """

    def _call(self, latest, current):
        # Block the packaging import so the naive fallback path runs.
        import sys

        with patch.dict(
            sys.modules, {"packaging": None, "packaging.version": None}
        ):
            return _is_newer(latest, current)

    def test_older_cached_latest_is_not_an_update(self):
        self.assertFalse(self._call("0.3.0", "0.3.1"))

    def test_equal_versions_are_not_an_update(self):
        self.assertFalse(self._call("0.3.1", "0.3.1"))

    def test_newer_latest_is_an_update(self):
        self.assertTrue(self._call("0.3.2", "0.3.1"))
        self.assertTrue(self._call("0.10.0", "0.9.9"))


class BannerContrastTests(unittest.TestCase):
    def test_headline_is_not_bold_black(self):
        # Terminals render bold black as bright black (grey) — unreadable on
        # the yellow background.
        from torrent_finder.ui import theme
        line = notice_line({"kind": "pip", "current": "0.1.0", "latest": "9.9.9"})
        self.assertIn("[banner]", line)
        self.assertIn("black on", theme.STYLES["banner"])
        self.assertNotIn("bold", theme.STYLES["banner"])


if __name__ == "__main__":
    unittest.main()
