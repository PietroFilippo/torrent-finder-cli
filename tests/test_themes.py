"""Themes: palettes fill every role, switching reaches every console, startup resolution."""

import io
import json
import unittest
import unittest.mock
import warnings

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirects saved settings before anything reads them
from isolation import isolate_store
from rich.color import Color, ColorSystem
from rich.text import Text

from torrent_finder import constants, settings_backup
from torrent_finder.ui import appearance, theme


def _luminance(color: str) -> float:
    triplet = Color.parse(color).get_truecolor()
    return 0.2126 * triplet.red + 0.7152 * triplet.green + 0.0722 * triplet.blue


class ThemeCase(unittest.TestCase):
    """Restores the default appearance after each test, whatever it applied."""

    def setUp(self):
        self.addCleanup(theme.apply, "quiet", focus="bar", density="comfortable")  # the suite's baseline


class PaletteTests(ThemeCase):
    def test_every_palette_gives_each_role_its_own_colour(self):
        for palette in theme.THEMES.values():
            with self.subTest(theme=palette.key):
                roles = (palette.accent, palette.sky, palette.steel, palette.deep, palette.fill)
                self.assertEqual(len(set(roles)), len(roles))
                for color in roles + (palette.good, palette.warn, palette.bad):
                    Color.parse(color)  # every value is a colour Rich understands
                self.assertNotEqual(palette.warn, palette.accent)  # Auto never looks like focus
                self.assertTrue(palette.note)

    def test_rules_recede_on_their_background(self):
        # Rules and bars sit between the page and the labels: darker than steel
        # on dark terminals, lighter than it on Paper's light page.
        for palette in theme.THEMES.values():
            if palette.accent.startswith("#"):
                with self.subTest(theme=palette.key):
                    if palette.light:
                        self.assertGreater(_luminance(palette.deep), _luminance(palette.steel))
                    else:
                        self.assertLess(_luminance(palette.deep), _luminance(palette.steel))

    def test_every_palette_belongs_to_a_design_with_a_default(self):
        self.assertEqual(theme.THEMES[theme.DEFAULT_THEME].design, "athanor")
        for key, design in theme.DESIGNS.items():
            with self.subTest(design=key):
                self.assertEqual(theme.THEMES[theme.DEFAULT_THEMES[key]].design, key)
                self.assertTrue(theme.palettes(key))
        self.assertEqual({p.design for p in theme.THEMES.values()}, set(theme.DESIGNS))
        self.assertEqual([p.key for p in theme.palettes("simple")],
                         ["quiet", "iris", "lagoon", "ember", "mono", "paper"])

    def test_colourways_describe_the_page_they_are_made_for(self):
        # Ink (the painting's lines) sits between the page and the text, so text stays readable over it.
        for palette in theme.palettes("athanor"):
            with self.subTest(theme=palette.key):
                for color in (palette.page, palette.text, palette.ink, palette.frame, palette.bar_bg):
                    Color.parse(color)
                self.assertLess(_luminance(palette.page), _luminance(palette.ink))
                self.assertLess(_luminance(palette.ink), _luminance(palette.steel))
                self.assertLess(_luminance(palette.bar_bg), _luminance(palette.page))

    def test_designs_bring_their_glyphs_and_frame(self):
        theme.apply("citrinitas")
        self.assertEqual((theme.CURSOR, theme.CRUMB, theme.CHECK, theme.SPINNER), ("@", " » ", "√", "line"))
        self.assertTrue(theme.FRAMED)
        self.assertEqual(theme.TEXT, theme.THEMES["citrinitas"].text)  # body text drawn in parchment
        theme.apply("quiet")
        self.assertEqual((theme.CURSOR, theme.CRUMB, theme.CHECK, theme.SPINNER), ("▍", " › ", "✓", "dots"))
        self.assertFalse(theme.FRAMED)
        self.assertEqual(theme.TEXT, "")  # the terminal's own foreground

    def test_quiet_blue_keeps_the_terminal_accent_and_state_colours(self):
        quiet = theme.THEMES["quiet"]
        self.assertEqual((quiet.accent, quiet.good, quiet.warn, quiet.bad),
                         ("bright_blue", "green", "yellow", "red"))


class ApplyTests(ThemeCase):
    def test_apply_rebinds_every_role_and_markup_style(self):
        iris = theme.apply("iris")
        self.assertIs(theme.PALETTE, iris)
        self.assertEqual(theme.ACCENT, iris.accent)
        self.assertEqual(theme.KEY, f"bold {iris.accent}")
        self.assertEqual(theme.MUTED, iris.steel)
        self.assertEqual(theme.RULE_STYLE, iris.deep)
        self.assertEqual(theme.SUBJECT, f"not bold {iris.sky}")
        self.assertEqual(theme.STYLES["accent"], iris.accent)
        self.assertEqual(theme.state_style("off"), iris.steel)

    def test_the_shared_and_offscreen_consoles_follow_the_theme(self):
        theme.apply("lagoon")
        self.assertEqual(constants.console.get_style("accent").color, Color.parse("#2DD4BF"))
        buffer = io.StringIO()
        with unittest.mock.patch.object(constants.console, "_color_system", ColorSystem.TRUECOLOR):
            constants.buffer_console(buffer, 20).print("[muted]label[/muted]")
        self.assertIn("38;2;110;156;163", buffer.getvalue())  # Lagoon's steel, #6E9CA3
        theme.apply("quiet")
        self.assertEqual(constants.console.get_style("accent").color, Color.parse("bright_blue"))

    def test_no_color_drops_colour_but_keeps_bold_focus(self):
        import os
        buffer = io.StringIO()
        with unittest.mock.patch.dict(os.environ, {"NO_COLOR": "1"}), \
             unittest.mock.patch.object(constants.console, "_color_system", ColorSystem.TRUECOLOR):
            constants.buffer_console(buffer, 40).print("[accent]x[/accent] [key]Enter[/key]")
        self.assertNotIn("38;", buffer.getvalue())
        self.assertIn("\x1b[1mEnter", buffer.getvalue())

    def test_state_and_seed_colours_follow_the_palette(self):
        theme.apply("ember")
        self.assertEqual(theme.state_style("auto"), "#FF8A3D")
        from torrent_finder.utils import leech_style, seed_style
        self.assertEqual(seed_style(3), "#FF8A3D")
        self.assertEqual(seed_style(0), theme.BAD)
        self.assertEqual(leech_style(2), theme.MUTED)

    def test_compact_density_drops_spacing_at_every_size(self):
        self.assertTrue(theme.roomy(40, 20))
        theme.apply(density="compact")
        self.assertFalse(theme.roomy(40, 20))
        self.assertEqual(theme.current()[2], "compact")
        theme.apply(density="comfortable")
        self.assertTrue(theme.roomy(40, 20))
        self.assertFalse(theme.roomy(19, 20))

    def test_unknown_settings_are_refused(self):
        with self.assertRaises(KeyError):
            theme.apply("neon")
        with self.assertRaises(ValueError):
            theme.apply(focus="glow")

    def test_a_header_status_keeps_its_own_colours(self):
        status = Text.from_markup("v1 · [warn]IP visible[/warn]")
        line = theme.header("Home", status, 60)
        styles = {line.plain[span.start:span.end]: str(span.style) for span in line.spans}
        warn_spans = [span for span in line.spans if str(span.style) == "warn"]
        self.assertTrue(warn_spans, styles)
        # The muted base comes first, so the warn span after it wins.
        muted_index = next(i for i, span in enumerate(line.spans) if str(span.style) == theme.MUTED)
        self.assertLess(muted_index, line.spans.index(warn_spans[0]))


class ResolutionTests(ThemeCase):
    def setUp(self):
        super().setUp()
        isolate_store(self)

    def test_names_match_keys_and_display_names_in_any_case(self):
        self.assertEqual(appearance.theme_key("Quiet Blue"), "quiet")
        self.assertEqual(appearance.theme_key(" PAPER "), "paper")
        self.assertEqual(appearance.theme_key("quiet-blue"), "quiet")
        self.assertIsNone(appearance.theme_key("neon"))
        self.assertIsNone(appearance.theme_key(None))

    def test_cli_beats_environment_beats_saved_beats_default(self):
        self.assertEqual(appearance.resolve(None, {})[0]["theme"], theme.DEFAULT_THEME)
        appearance.save("iris", "fill", "compact")
        resolved, source, notice = appearance.resolve(None, {})
        self.assertEqual((resolved, source, notice),
                         ({"theme": "iris", "focus": "fill", "density": "compact", "painting": "dore-satan",
                           "fonts": appearance.DEFAULT_FONTS, "profile": appearance.DEFAULT_PROFILE},
                          "saved", ""))
        resolved, source, _ = appearance.resolve(None, {appearance.ENV: "ember"})
        self.assertEqual((resolved["theme"], resolved["focus"], source), ("ember", "fill", "env"))
        resolved, source, _ = appearance.resolve("mono", {appearance.ENV: "ember"})
        self.assertEqual((resolved["theme"], source), ("mono", "cli"))

    def test_an_unknown_environment_theme_is_named_and_ignored(self):
        resolved, source, notice = appearance.resolve(None, {appearance.ENV: "neon"})
        self.assertEqual((resolved["theme"], source), (theme.DEFAULT_THEME, "saved"))
        self.assertIn("neon", notice)
        self.assertIn("lagoon", notice)

    def test_odd_saved_values_fall_back_to_defaults(self):
        self.assertEqual(appearance.normalize({"theme": "neon", "focus": 3, "density": "huge"}), appearance.DEFAULTS)
        self.assertEqual(appearance.normalize("paper"), appearance.DEFAULTS)

    def test_startup_applies_the_resolved_appearance(self):
        appearance.save("paper", "fill", "compact")
        self.assertEqual(appearance.apply_startup(None, {}), "")
        palette, focus, density = theme.current()
        self.assertEqual((palette.key, focus, density), ("paper", "fill", "compact"))
        self.assertTrue(theme.FILL_FOCUS)
        appearance.apply_startup("lagoon", {})
        self.assertEqual(theme.PALETTE.key, "lagoon")
        self.assertEqual(appearance.override_source(), "cli")

    def test_the_cli_flag_offers_every_theme(self):
        from torrent_finder.main import _build_parser
        self.assertEqual(_build_parser().parse_args(["--theme", "Iris"]).theme, "iris")
        with self.assertRaises(SystemExit), unittest.mock.patch("sys.stderr", io.StringIO()):
            _build_parser().parse_args(["--theme", "neon"])


class BackupTests(unittest.TestCase):
    def test_appearance_is_a_portable_preference(self):
        settings_backup.validate_payload({"settings": {"appearance": {"theme": "iris", "focus": "bar"}}})
        for bad in ({"theme": 3}, {"colour": "red"}, "iris"):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                settings_backup.validate_payload({"settings": {"appearance": bad}})
        json.dumps(appearance.DEFAULTS)  # stored as plain JSON


if __name__ == "__main__":
    unittest.main()
