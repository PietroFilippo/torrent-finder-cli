"""The Windows Terminal profile: its GUID, colour scheme, fragment files and the Appearance rows."""

import io
import json
import shutil
import subprocess
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirects saved settings before anything reads them
from isolation import isolate_store
from readchar import key as K
from rich.console import Console

from torrent_finder import terminal_profile
from torrent_finder.ui import appearance, selector, theme

COLOUR_TABLE = ("black", "red", "green", "yellow", "blue", "purple", "cyan", "white",
                "brightBlack", "brightRed", "brightGreen", "brightYellow",
                "brightBlue", "brightPurple", "brightCyan", "brightWhite")


class ProfileCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.environ = {"LOCALAPPDATA": folder.name, "WT_PROFILE_ID": ""}
        self.patch(terminal_profile, "_package_family", return_value="")
        self.install_font = self.patch(terminal_profile, "install_font")
        self.patch(terminal_profile, "supported", return_value=True)
        self.patch(terminal_profile, "font_installed", return_value=False)
        environ = patch.dict(terminal_profile.os.environ, self.environ)
        environ.start()
        self.addCleanup(environ.stop)

    def patch(self, target, name, **kwargs):
        patcher = patch.object(target, name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def fragment(self) -> dict:
        return json.loads(terminal_profile.fragment_path().read_text(encoding="utf-8"))

    def pictures(self) -> list[str]:
        return sorted(p.name for p in terminal_profile.folder().glob("*.png"))


class FragmentTests(ProfileCase):
    def test_the_guid_follows_windows_terminals_rule(self):
        # Microsoft's documented example: the "Git Bash" profile of the "Git" fragment.
        self.assertEqual(terminal_profile.profile_guid("Git", "Git Bash"), "{2ece5bfe-50ed-5f3a-ab87-5cd4baafed2b}")
        self.assertEqual(terminal_profile.PROFILE_GUID, terminal_profile.profile_guid("torrent-finder", "torrent-finder"))

    def test_the_folder_is_windows_terminals_per_user_fragment_folder(self):
        path = terminal_profile.fragment_path()
        self.assertEqual(path.parent, Path(self.environ["LOCALAPPDATA"], "Microsoft", "Windows Terminal",
                                           "Fragments", "torrent-finder"))
        self.assertFalse(terminal_profile.installed())

    def test_an_athanor_profile_has_the_colourway_painting_and_font(self):
        terminal_profile.font_installed.return_value = True
        palette = theme.THEMES["rubedo"]
        terminal_profile.write(palette, "dore-raven")
        data = self.fragment()
        profile, scheme = data["profiles"][0], data["schemes"][0]
        self.assertEqual(profile["guid"], terminal_profile.PROFILE_GUID)
        self.assertEqual(profile["colorScheme"], scheme["name"])
        self.assertEqual((scheme["background"], scheme["foreground"]), (palette.page, palette.text))
        self.assertEqual(profile["backgroundImage"], "torrent-finder-dore-raven-rubedo.png")  # beside the fragment
        self.assertEqual(self.pictures(), ["torrent-finder-dore-raven-rubedo.png"])
        self.assertEqual(profile["font"]["face"], "PxPlus IBM VGA 8x16")
        self.assertEqual(profile["intenseTextStyle"], "bright")  # no smeared made-up bold
        self.assertIn("torrent_finder", profile["commandline"] + profile.get("startingDirectory", ""))
        self.assertTrue(terminal_profile.installed())

    def test_every_scheme_is_complete_in_hex(self):
        for palette in theme.THEMES.values():
            with self.subTest(palette=palette.key):
                scheme = terminal_profile.scheme(palette)
                for name in COLOUR_TABLE + ("background", "foreground", "cursorColor", "selectionBackground"):
                    self.assertRegex(scheme[name], r"^#[0-9A-Fa-f]{6}$", name)
        self.assertEqual(terminal_profile.scheme(theme.THEMES["paper"])["background"], "#FAFAFA")  # a light page

    def test_rewriting_replaces_the_picture_and_simple_has_none(self):
        terminal_profile.write(theme.THEMES["citrinitas"], "dore-satan")
        terminal_profile.write(theme.THEMES["citrinitas"], "flammarion")
        self.assertEqual(self.pictures(), ["torrent-finder-flammarion-citrinitas.png"])
        terminal_profile.write(theme.THEMES["paper"], "flammarion")  # paintings belong to Athanor
        self.assertEqual(self.pictures(), [])
        self.assertNotIn("backgroundImage", self.fragment()["profiles"][0])
        self.assertNotIn("font", self.fragment()["profiles"][0])  # the font is not installed
        terminal_profile.remove()
        self.assertFalse(terminal_profile.folder().exists())

    def test_the_font_is_installed_only_when_asked_and_missing(self):
        terminal_profile.write(theme.THEMES["citrinitas"], "none")
        self.install_font.assert_not_called()
        terminal_profile.write(theme.THEMES["citrinitas"], "none", add_font=True)
        self.install_font.assert_called_once()

    def test_the_bundled_font_and_its_licence_ship(self):
        self.assertTrue((terminal_profile.FONTS / terminal_profile.FONT_FILE).is_file())
        licence = (terminal_profile.FONTS / "LICENSE.TXT").read_text(encoding="utf-8", errors="replace")
        self.assertIn("Attribution-ShareAlike 4.0", licence)

    def test_in_profile_reads_windows_terminals_profile_id(self):
        self.assertTrue(terminal_profile.in_profile({"WT_PROFILE_ID": terminal_profile.PROFILE_GUID.upper()}))
        self.assertFalse(terminal_profile.in_profile({"WT_PROFILE_ID": "{0000}"}))


class StorePythonTests(ProfileCase):
    """Python from the Microsoft Store keeps the folders it makes under AppData in a private copy."""

    def setUp(self):
        super().setUp()
        self.patch(terminal_profile, "_package_family", return_value="Python.Store_x")
        self.commands = []
        self.patch(terminal_profile.subprocess, "run", side_effect=self.cmd)

    def cmd(self, args, **_kwargs):
        """cmd runs outside the container: its folders are real."""
        self.commands.append(args[3])
        if args[3] == "mkdir":
            Path(args[4]).mkdir(parents=True, exist_ok=True)
        elif args[3] == "rmdir":
            shutil.rmtree(args[-1], ignore_errors=True)
        return subprocess.CompletedProcess(args, 0)

    def private(self, path: Path) -> Path:
        return terminal_profile._private_copy(path)

    def test_the_private_copy_sits_in_the_package_cache(self):
        self.assertEqual(self.private(terminal_profile.fragment_path()),
                         Path(self.environ["LOCALAPPDATA"], "Packages", "Python.Store_x", "LocalCache", "Local",
                              "Microsoft", "Windows Terminal", "Fragments", "torrent-finder", "torrent-finder.json"))

    def test_a_profile_only_python_sees_is_replaced_by_a_real_one(self):
        stale = self.private(terminal_profile.fragment_path())
        stale.parent.mkdir(parents=True)
        stale.write_text("{}", encoding="utf-8")
        terminal_profile.fragment_path().parent.mkdir(parents=True)  # the merged view Python reads
        terminal_profile.fragment_path().write_text("{}", encoding="utf-8")
        self.assertFalse(terminal_profile.installed())  # Windows Terminal cannot see it: Add again
        terminal_profile.write(theme.THEMES["rubedo"], "smith-hermit")
        self.assertEqual(self.commands, ["mkdir"])
        self.assertFalse(Path(self.environ["LOCALAPPDATA"], "Packages", "Python.Store_x", "LocalCache",
                              "Local", "Microsoft").exists())  # the stale copy and its empty parents
        self.assertTrue(terminal_profile.installed())
        terminal_profile.remove()
        self.assertEqual(self.commands, ["mkdir", "rmdir"])
        self.assertFalse(terminal_profile.folder().exists())

    def test_a_write_windows_kept_private_is_an_error(self):
        path = terminal_profile.fragment_path()
        self.private(path).parent.mkdir(parents=True)
        self.private(path).write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(OSError, "Windows Terminal cannot see it"):
            terminal_profile._check_real(path)


class AppearanceRowTests(ProfileCase):
    def setUp(self):
        super().setUp()
        isolate_store(self)
        theme.apply("citrinitas", focus="bar", density="comfortable")

    def capture(self) -> list:
        captured = []
        with patch("torrent_finder.ui.selector.arrow_select", side_effect=lambda items, **kw: captured.append(items)):
            appearance.appearance_menu()
        return captured[0]

    def run_menu(self, *values, confirm=True):
        """Walk to each row *value* in turn and press Enter on it, then leave."""
        keys, position = [], ("theme", theme.PALETTE.key)
        items = self.capture()
        for value in values:
            start = next(i for i, item in enumerate(items) if item.value == position)
            target = next(i for i, item in enumerate(items) if item.value == value)
            step = K.DOWN if target > start else K.UP
            span = items[start + 1:target + 1] if target > start else items[target:start]
            keys += [step] * sum(item.enabled for item in span) + [K.ENTER]
            position = value
        screen = Console(file=io.StringIO(), width=100, height=40, color_system=None)
        with patch.object(selector, "console", screen), \
             patch.object(selector, "_render", return_value=True), \
             patch.object(selector.sys, "stdout", io.StringIO()), \
             patch("torrent_finder.ui.prompts.confirm_prompt", return_value=confirm) as asked, \
             patch.object(selector.readchar, "readkey", side_effect=keys + [K.ESC]):
            appearance.appearance_menu()
        return asked

    def test_windows_offers_the_profile_and_it_follows_later_choices(self):
        self.assertIn(("profile", "add"), [item.value for item in self.capture()])
        asked = self.run_menu(("profile", "add"))
        self.assertIn("PxPlus IBM VGA 8x16", asked.call_args.args[0])  # says it installs the font
        self.assertEqual(self.fragment()["schemes"][0]["name"], "torrent-finder Citrinitas")
        self.install_font.assert_called_once()
        self.assertIn(("profile", "remove"), [item.value for item in self.capture()])

        self.run_menu(("theme", "viriditas"))
        self.assertEqual(self.fragment()["schemes"][0]["name"], "torrent-finder Viriditas")
        self.run_menu(("painting", "smith-hermit"))
        self.assertEqual(self.pictures(), ["torrent-finder-smith-hermit-viriditas.png"])

        self.run_menu(("profile", "remove"))
        self.assertFalse(terminal_profile.installed())

    def test_declining_the_confirmation_writes_nothing(self):
        self.run_menu(("profile", "add"), confirm=False)
        self.assertFalse(terminal_profile.folder().exists())
        self.install_font.assert_not_called()

    def test_other_systems_get_no_profile_rows(self):
        terminal_profile.supported.return_value = False
        values = [item.value for item in self.capture()]
        self.assertNotIn(("profile", "add"), values)
        self.assertIn(appearance.PAINTING_HELP, next(item for item in self.capture()
                                                     if item.value == ("painting", "dore-satan")).description)


if __name__ == "__main__":
    unittest.main()
