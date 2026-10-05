"""The Windows Terminal profile: its GUID, colour scheme, fragment files and the Appearance rows."""

import io
import json
import shutil
import subprocess
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import Mock, patch

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
        self.patch(terminal_profile.shutil, "which", return_value=None)  # as from a source checkout
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

    def test_fonts_are_installed_only_when_asked_and_missing(self):
        terminal_profile.write(theme.THEMES["citrinitas"], "none")
        self.install_font.assert_not_called()
        terminal_profile.write(theme.THEMES["citrinitas"], "none", add_font=True)
        bundled = [font for font in terminal_profile.FONTS.values() if font.file]
        self.assertEqual([call.args[0] for call in self.install_font.call_args_list], bundled)

    def test_the_bundled_fonts_and_their_licence_ship(self):
        for font in terminal_profile.FONTS.values():
            if font.file:
                self.assertTrue((terminal_profile.FONT_DIR / font.file).is_file(), font.file)
        licence = (terminal_profile.FONT_DIR / "LICENSE.TXT").read_text(encoding="utf-8", errors="replace")
        self.assertIn("Attribution-ShareAlike 4.0", licence)
        credits = (terminal_profile.FONT_DIR / "README.md").read_text(encoding="utf-8")
        for font in terminal_profile.FONTS.values():
            if font.file:
                self.assertIn(font.file, credits)

    def test_in_profile_reads_windows_terminals_profile_id(self):
        self.assertTrue(terminal_profile.in_profile({"WT_PROFILE_ID": terminal_profile.PROFILE_GUID.upper()}))
        self.assertFalse(terminal_profile.in_profile({"WT_PROFILE_ID": "{0000}"}))


class RefreshTests(ProfileCase):
    """Windows Terminal reloads its settings, fragments included, when settings.json's time changes."""

    def settings(self, *parts) -> Path:
        path = Path(self.environ["LOCALAPPDATA"], *parts, "settings.json")
        path.parent.mkdir(parents=True)
        path.write_bytes(b'{"profiles": {}}\r\n')
        terminal_profile.os.utime(path, (1_000_000_000, 1_000_000_000))
        return path

    def test_every_terminal_build_is_found(self):
        stable = self.settings("Packages", "Microsoft.WindowsTerminal_8wekyb3d8bbwe", "LocalState")
        preview = self.settings("Packages", "Microsoft.WindowsTerminalPreview_8wekyb3d8bbwe", "LocalState")
        unpackaged = self.settings("Microsoft", "Windows Terminal")
        self.assertEqual(terminal_profile.settings_files(), [stable, preview, unpackaged])

    def test_refreshing_changes_only_the_modification_time(self):
        path = self.settings("Packages", "Microsoft.WindowsTerminal_8wekyb3d8bbwe", "LocalState")
        self.assertTrue(terminal_profile.refresh())
        self.assertGreater(path.stat().st_mtime, 1_000_000_000)
        self.assertEqual(path.read_bytes(), b'{"profiles": {}}\r\n')

    def test_without_windows_terminal_nothing_is_told(self):
        self.assertFalse(terminal_profile.refresh())


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


class FontTests(ProfileCase):
    def have(self, *faces):
        """Windows lists these bundled faces; fonts the app does not bundle always count."""
        listed = set(faces)
        terminal_profile.font_installed.side_effect = lambda font=None: not font.file or font.face in listed
        self.install_font.side_effect = lambda font, environ=None: listed.add(font.face)

    def test_each_design_offers_its_own_fonts_its_default_first(self):
        for design in theme.DESIGNS:
            fonts = terminal_profile.fonts(design)
            self.assertGreaterEqual(len(fonts), 4)
            self.assertEqual(fonts[0], terminal_profile.default_font(design))
            self.assertTrue(all(font.pixel == (design == "athanor") for font in fonts))

    def test_pixel_sizes_are_whole_and_half_multiples_of_the_cell(self):
        vga, xga = terminal_profile.FONTS["ibm-vga-8x16"], terminal_profile.FONTS["ibm-xga-12x20"]
        self.assertEqual([vga.points(size) for size in vga.sizes], [12, 18, 24, 36])
        self.assertEqual(xga.points(1), 15)
        self.assertEqual(vga.points(7), 12)  # an unknown size is the default
        self.assertEqual(vga.size_label(2), "×2 · 24 pt")
        self.assertEqual(terminal_profile.FONTS["ast-premium-exec"].size_label(1.5), "×1.5 · 21.4 pt")
        self.assertEqual(terminal_profile.FONTS["consolas"].size_label(14), "14 pt")

    def test_pixel_fonts_draw_unsmoothed_and_simple_gets_its_own_font(self):
        self.have(*(font.face for font in terminal_profile.FONTS.values()))
        terminal_profile.write(theme.THEMES["citrinitas"], "none", font=terminal_profile.FONTS["ibm-xga-12x20"], size=2)
        profile = self.fragment()["profiles"][0]
        self.assertEqual(profile["font"], {"face": "PxPlus IBM XGA-AI 12x20", "size": 30})
        self.assertEqual((profile["antialiasingMode"], profile["intenseTextStyle"]), ("aliased", "bright"))
        terminal_profile.write(theme.THEMES["citrinitas"], "none", font=terminal_profile.FONTS["ast-premium-exec"],
                               size=1.5)
        self.assertEqual(self.fragment()["profiles"][0]["font"]["size"], 21.38)
        terminal_profile.write(theme.THEMES["quiet"], "none")
        profile = self.fragment()["profiles"][0]
        self.assertEqual(profile["font"], {"face": "Cascadia Mono", "size": 12})  # not the VGA font any more
        self.assertNotIn("antialiasingMode", profile)

    def test_a_pixel_font_windows_lacks_is_left_out(self):
        self.have()
        terminal_profile.write(theme.THEMES["citrinitas"], "none", font=terminal_profile.FONTS["ibm-vga-9x16"])
        self.assertNotIn("font", self.fragment()["profiles"][0])

    def test_installing_adds_the_missing_fonts_once(self):
        self.have("PxPlus IBM VGA 8x16")
        installed = terminal_profile.install_fonts()
        self.assertEqual([font.key for font in installed],
                         [font.key for font in terminal_profile.fonts("athanor")][1:])
        self.assertEqual(terminal_profile.install_fonts(), [])

    def test_saved_fonts_are_kept_per_design_and_checked(self):
        fonts = appearance.normalize({"fonts": {"athanor": {"font": "consolas", "size": 2},
                                                "simple": {"font": "cascadia-code", "size": 16}}})["fonts"]
        self.assertEqual(fonts, {"athanor": {"font": "ibm-vga-8x16", "size": 2},  # Consolas is not Athanor's
                                 "simple": {"font": "cascadia-code", "size": 16}})
        fonts = appearance.normalize({"fonts": {"athanor": {"font": "ibm-vga-9x16", "size": 13}}})["fonts"]
        self.assertEqual(fonts["athanor"], {"font": "ibm-vga-9x16", "size": 1})
        self.assertEqual(fonts["simple"], appearance.DEFAULT_FONTS["simple"])

    def test_the_settings_details_name_the_font(self):
        from torrent_finder.ui import inspector
        theme.apply("citrinitas")
        self.addCleanup(theme.apply, "quiet")
        text = " ".join(line.plain for line in inspector.appearance_details())
        self.assertIn("PxPlus IBM VGA 8x16 · ×1 · 12 pt", text)


class PlainLookTests(ProfileCase):
    def test_a_plain_profile_keeps_windows_terminals_page_and_font(self):
        terminal_profile.font_installed.return_value = True
        terminal_profile.write(theme.THEMES["citrinitas"], "dore-satan")
        self.assertEqual(len(self.pictures()), 1)
        terminal_profile.write(theme.THEMES["citrinitas"], "dore-satan", plain=True)
        data = self.fragment()
        profile = data["profiles"][0]
        for key in ("colorScheme", "backgroundImage", "font", "antialiasingMode"):
            self.assertNotIn(key, profile)
        self.assertEqual(data["schemes"], [])
        self.assertEqual(self.pictures(), [])  # the picture goes with the look
        self.assertEqual(profile["guid"], terminal_profile.PROFILE_GUID)

    def test_only_another_profiles_tab_counts_as_another_tab(self):
        other = {"WT_SESSION": "{1}", "WT_PROFILE_ID": "{61c54bbd-c2c6-5271-96e7-009a87ff44bf}"}
        self.assertTrue(terminal_profile.in_other_tab(other))
        self.assertFalse(terminal_profile.in_other_tab({**other, "WT_PROFILE_ID": terminal_profile.PROFILE_GUID}))
        self.assertFalse(terminal_profile.in_other_tab({"WT_PROFILE_ID": "{1}"}))  # not in Windows Terminal

    def test_opening_a_tab_names_the_profile_and_passes_the_arguments(self):
        terminal_profile.shutil.which.return_value = r"C:\wt.exe"
        with patch.object(terminal_profile.subprocess, "Popen") as popen:
            self.assertTrue(terminal_profile.open_tab([]))
            self.assertEqual(popen.call_args.args[0], [r"C:\wt.exe", "-w", "0", "new-tab", "-p", "torrent-finder"])
            self.assertTrue(terminal_profile.open_tab(["-q", "dune; part two"]))
            tab = popen.call_args.args[0]
        self.assertEqual(tab[:6], [r"C:\wt.exe", "-w", "0", "new-tab", "-p", "torrent-finder"])
        self.assertEqual(tab[-2:], ["-q", "dune\\; part two"])  # ";" would start Windows Terminal's next command
        self.assertEqual(tab[6:-2], terminal_profile.command())

    def test_without_windows_terminal_or_when_it_fails_the_app_stays(self):
        terminal_profile.shutil.which.return_value = None
        self.assertFalse(terminal_profile.open_tab([]))
        terminal_profile.shutil.which.return_value = r"C:\wt.exe"
        with patch.object(terminal_profile.subprocess, "Popen", side_effect=OSError("gone")):
            self.assertFalse(terminal_profile.open_tab([]))

    def test_saved_profile_choices_are_checked(self):
        self.assertEqual(appearance.normalize({"profile": {"look": "neon", "open_from_tabs": "yes"}})["profile"],
                         {"look": "full", "open_from_tabs": False})
        self.assertEqual(appearance.normalize({"profile": {"look": "plain", "open_from_tabs": True}})["profile"],
                         {"look": "plain", "open_from_tabs": True})


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
        build = selector._build_panel
        self.footers = []

        def record(*args, **kwargs):
            self.footers.append(args[4])  # the footer, resolved for this frame
            return build(*args, **kwargs)

        with patch.object(selector, "console", screen), \
             patch.object(selector, "_build_panel", side_effect=record), \
             patch.object(selector, "_render", return_value=True), \
             patch.object(selector.sys, "stdout", io.StringIO()), \
             patch("torrent_finder.ui.prompts.confirm_prompt", return_value=confirm) as asked, \
             patch.object(selector.readchar, "readkey", side_effect=keys + [K.ESC]):
            appearance.appearance_menu()
        return asked

    def test_windows_offers_the_profile_and_it_follows_later_choices(self):
        self.assertIn(("profile", "add"), [item.value for item in self.capture()])
        asked = self.run_menu(("profile", "add"))
        self.assertIn("PxPlus IBM VGA 8x16", asked.call_args.args[0])  # names the font
        self.assertIn("installed for your account", asked.call_args.args[0])
        self.assertEqual(self.fragment()["schemes"][0]["name"], "torrent-finder Citrinitas")
        self.assertEqual(self.install_font.call_count, len(terminal_profile.missing_fonts()))
        self.assertIn(("profile", "remove"), [item.value for item in self.capture()])

        self.run_menu(("theme", "viriditas"))
        self.assertEqual(self.fragment()["schemes"][0]["name"], "torrent-finder Viriditas")
        self.run_menu(("painting", "smith-hermit"))
        self.assertEqual(self.pictures(), ["torrent-finder-smith-hermit-viriditas.png"])

        self.run_menu(("profile", "remove"))
        self.assertFalse(terminal_profile.installed())

    def test_a_running_terminal_follows_at_once_else_after_a_restart(self):
        self.run_menu(("profile", "add"))
        for told, theme_key, expected in ((True, "rubedo", appearance.FOLLOWS_NOW),
                                          (False, "albedo", appearance.FOLLOWS_LATER)):
            with self.subTest(told=told), patch.object(terminal_profile, "refresh", return_value=told) as refresh:
                self.run_menu(("theme", theme_key))
            refresh.assert_called_once()
            self.assertIn(expected, self.footers[-1])
            self.assertEqual(self.fragment()["schemes"][0]["name"], f"torrent-finder {theme.THEMES[theme_key].name}")

    def test_declining_the_confirmation_writes_nothing(self):
        self.run_menu(("profile", "add"), confirm=False)
        self.assertFalse(terminal_profile.folder().exists())
        self.install_font.assert_not_called()

    def test_font_and_size_rows_follow_the_design_on_screen(self):
        values = [item.value for item in self.capture()]
        self.assertIn(("font", "ibm-xga-12x20"), values)
        self.assertNotIn(("font", "consolas"), values)
        self.assertEqual([value for value in values if isinstance(value, tuple) and value[0] == "size"],
                         [("size", size) for size in terminal_profile.PIXEL_SCALES])

    def test_choosing_a_font_installs_them_and_restyles_the_profile(self):
        self.run_menu(("profile", "add"))
        terminal_profile.font_installed.return_value = True
        nine = terminal_profile.FONTS["ibm-vga-9x16"]
        with patch.object(terminal_profile, "install_fonts", return_value=[nine]) as fonts, \
             patch.object(terminal_profile, "refresh", return_value=True) as refresh:
            self.run_menu(("font", "ibm-vga-9x16"))
            fonts.assert_called_once()
            refresh.assert_called_once()
            self.assertIn(appearance.NEW_FONTS, self.footers[-1])
            self.assertEqual(self.fragment()["profiles"][0]["font"], {"face": "PxPlus IBM VGA 9x16", "size": 12})
            self.run_menu(("size", 2))
        self.assertEqual(self.fragment()["profiles"][0]["font"]["size"], 24)
        self.assertEqual(appearance.saved()["fonts"]["athanor"], {"font": "ibm-vga-9x16", "size": 2})

    def test_a_font_chosen_without_the_profile_is_saved_for_it(self):
        self.run_menu(("font", "toshiba-txl1"))
        self.assertIn(appearance.FONT_SAVED, self.footers[-1])
        self.assertEqual(appearance.saved()["fonts"]["athanor"]["font"], "toshiba-txl1")
        self.assertFalse(terminal_profile.folder().exists())
        self.install_font.assert_not_called()

    def test_athanor_offers_a_plain_look_that_drops_the_page_painting_and_font(self):
        values = [item.value for item in self.capture()]
        self.assertIn(("look", "plain"), values)
        self.assertNotIn(("open", True), values)  # only once the profile exists
        self.run_menu(("profile", "add"))
        self.run_menu(("look", "plain"))
        self.assertNotIn("colorScheme", self.fragment()["profiles"][0])
        self.assertEqual(appearance.saved()["profile"]["look"], "plain")
        items = self.capture()
        self.assertFalse([item for item in items if isinstance(item.value, tuple) and item.value[0] in ("font", "size")])
        painting = next(item for item in items if item.value == ("painting", "dore-satan"))
        self.assertIn(appearance.PLAIN_PAINTING_HELP, painting.description)
        self.run_menu(("look", "full"))
        self.assertEqual(self.fragment()["profiles"][0]["colorScheme"], "torrent-finder Citrinitas")

    def test_simple_has_no_look_choice(self):
        theme.apply("quiet")
        self.assertFalse([item for item in self.capture()
                          if isinstance(item.value, tuple) and item.value[0] == "look"])

    def test_opening_from_other_tabs_is_a_saved_switch(self):
        self.run_menu(("profile", "add"))
        self.run_menu(("open", True))
        self.assertTrue(appearance.saved()["profile"]["open_from_tabs"])
        self.assertIn(("open", False), [item.value for item in self.capture()])

    def test_other_systems_get_no_profile_rows(self):
        terminal_profile.supported.return_value = False
        values = [item.value for item in self.capture()]
        self.assertNotIn(("profile", "add"), values)
        self.assertFalse([value for value in values if isinstance(value, tuple) and value[0] in ("font", "size")])
        self.assertIn(appearance.PAINTING_HELP, next(item for item in self.capture()
                                                     if item.value == ("painting", "dore-satan")).description)


class HandOffTests(unittest.TestCase):
    """The command typed in another Windows Terminal tab opens the profile's tab, when asked to."""

    def run_main(self, *, other_tab=True, tty=True, setting=True, installed=True, opened=True):
        from torrent_finder import main as app
        saved = {**appearance.DEFAULTS, "profile": {"look": "full", "open_from_tabs": setting}}
        with patch.object(terminal_profile, "supported", return_value=True), \
             patch.object(terminal_profile, "in_other_tab", return_value=other_tab), \
             patch.object(terminal_profile, "installed", return_value=installed), \
             patch.object(terminal_profile, "open_tab", return_value=opened) as open_tab, \
             patch.object(appearance, "saved", return_value=saved), \
             patch.object(app.sys, "stdin", Mock(isatty=Mock(return_value=tty))), \
             patch("sys.argv", ["tf", "-q", "dune"]), \
             patch.object(app, "_main_loop") as loop, \
             patch.object(app, "record_session_start") as stats, \
             patch.object(app, "add_runtime_seconds"), patch.object(app, "console"):
            app.main()
        return open_tab, loop, stats

    def test_the_app_moves_to_the_profiles_tab_with_its_arguments(self):
        open_tab, loop, stats = self.run_main()
        open_tab.assert_called_once_with(["-q", "dune"])
        loop.assert_not_called()
        stats.assert_not_called()  # the new tab's run counts the session

    def test_otherwise_it_runs_here(self):
        for case in ({"other_tab": False}, {"tty": False}, {"setting": False}, {"installed": False},
                     {"opened": False}):
            with self.subTest(**case):
                open_tab, loop, _ = self.run_main(**case)
                loop.assert_called_once()
                if "opened" not in case:
                    open_tab.assert_not_called()


if __name__ == "__main__":
    unittest.main()
