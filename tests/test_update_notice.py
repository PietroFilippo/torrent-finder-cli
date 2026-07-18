import unittest
import warnings

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from rich.text import Text

from torrent_finder.updates import notice_line


class UpdateNoticeTests(unittest.TestCase):
    def test_no_info_gives_empty_line(self):
        self.assertEqual(notice_line(None), "")

    def test_notice_survives_a_dim_base_style(self):
        # The provider-menu footer renders with a dim base style; the notice
        # must carry "not dim" so it stays bright there.
        line = notice_line({"kind": "pip", "current": "0.1.0", "latest": "9.9.9"})
        self.assertIn("not dim", line)
        self.assertIn("on yellow", line)
        self.assertIn("9.9.9", line)
        Text.from_markup(line, style="dim")  # must parse as valid markup

    def test_each_kind_names_its_update_path(self):
        git = notice_line({"kind": "git", "behind": 2})
        self.assertIn("git pull", git)
        self.assertIn("2 commits behind", git)

        binary = notice_line({"kind": "binary", "current": "0.1.0", "latest": "9.9.9"})
        self.assertIn("releases", binary)


if __name__ == "__main__":
    unittest.main()
