import json
import unittest
import warnings
from unittest.mock import Mock, patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from rich.text import Text

from torrent_finder import updates
from torrent_finder.updates import _is_newer, notice_line


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
        line = notice_line({"kind": "pip", "current": "0.1.0", "latest": "9.9.9"})
        self.assertIn("[not dim black on yellow]", line)
        self.assertNotIn("bold black", line)


class PipxUpgradeExitCodeTests(unittest.TestCase):
    def test_locked_launcher_failure_still_reports_success(self):
        # On Windows, pipx exits nonzero when it can't replace the running
        # .local/bin launcher even though the venv upgraded fine. The flow
        # must trust the installed version over the exit code.
        def fake_run(cmd, **kwargs):
            result = Mock()
            if cmd[:2] == ["pipx", "upgrade"]:
                result.returncode = 1  # WinError 32 replacing the launcher
            else:  # pipx list --json
                result.returncode = 0
                result.stdout = json.dumps({
                    "venvs": {
                        "torrent-finder-cli": {
                            "metadata": {
                                "main_package": {"package_version": "9.9.9"}
                            }
                        }
                    }
                })
            return result

        # Pin the running version: a source checkout that was never built
        # reports "0+unknown" (e.g. on CI), which _is_newer refuses to compare.
        with patch.object(updates, "__version__", "0.1.0"), patch.object(
            updates, "_pipx_install", return_value=True
        ), patch.object(updates.subprocess, "run", side_effect=fake_run):
            ok, msg = updates.run_update({"kind": "pip"})

        self.assertTrue(ok)
        self.assertIn("v9.9.9", msg)
        self.assertIn("restart", msg)

    def test_real_failure_still_reports_failure(self):
        def fake_run(cmd, **kwargs):
            result = Mock()
            result.returncode = 1
            result.stdout = ""
            return result

        with patch.object(updates, "_pipx_install", return_value=True), patch.object(
            updates.subprocess, "run", side_effect=fake_run
        ):
            ok, msg = updates.run_update({"kind": "pip"})

        self.assertFalse(ok)
        self.assertIn("pipx upgrade torrent-finder-cli", msg)


if __name__ == "__main__":
    unittest.main()
