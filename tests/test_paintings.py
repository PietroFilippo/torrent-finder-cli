"""The Athanor paintings: the catalogue, the 1-bit PNG codec, recolouring and the Appearance rows."""

import io
import struct
import tempfile
import unittest
import warnings
import zlib
from pathlib import Path
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirects saved settings before anything reads them
from isolation import isolate_store
from readchar import key as K
from rich.console import Console

from torrent_finder import paintings, settings_backup, state
from torrent_finder.ui import appearance, selector, theme


def chunks(blob: bytes) -> dict:
    """A PNG's chunks by type, checking every CRC on the way."""
    found, position = {}, 8
    while position < len(blob):
        length, kind = struct.unpack(">I4s", blob[position:position + 8])
        body = blob[position + 8:position + 8 + length]
        (crc,) = struct.unpack(">I", blob[position + 8 + length:position + 12 + length])
        assert crc == zlib.crc32(kind + body) & 0xFFFFFFFF, kind
        found.setdefault(kind, b"")
        found[kind] += body
        position += 12 + length
    return found


class CatalogTests(unittest.TestCase):
    def test_every_painting_is_public_domain_credited_and_present(self):
        catalog = paintings.catalog()
        self.assertGreaterEqual(len(catalog), 10)
        self.assertEqual(next(iter(catalog)), paintings.DEFAULT)
        self.assertGreaterEqual(sum(entry.artist == "Gustave Doré" for entry in catalog.values()), 6)
        for key, entry in catalog.items():
            with self.subTest(key=key):
                self.assertEqual(entry.licence, "Public domain")
                self.assertTrue(entry.source.startswith("https://commons.wikimedia.org/"))
                width, height, rows = paintings.bitmap(key)
                self.assertEqual(height, 560)
                self.assertLessEqual(width, 560)
                self.assertEqual(len(rows), height)
                self.assertIn(entry.year, entry.credit)

    def test_keys_are_known_paintings_or_none(self):
        self.assertEqual(paintings.painting_key("dore-raven"), "dore-raven")
        self.assertEqual(paintings.painting_key("none"), "none")
        self.assertIsNone(paintings.painting_key("mona-lisa"))
        self.assertIsNone(paintings.painting_key(3))


class PngTests(unittest.TestCase):
    ROWS = [bytes([0b10100000]), bytes([0b01000000])]  # a 3x2 checker

    def test_written_pngs_read_back(self):
        blob = paintings.write_png(3, 2, self.ROWS, ((0, 0, 0), (255, 255, 255)))
        self.assertEqual(paintings.read_png(blob), (3, 2, self.ROWS))
        found = chunks(blob)
        self.assertEqual(struct.unpack(">IIBB", found[b"IHDR"][:10]), (3, 2, 1, 3))  # 1-bit, palette
        self.assertEqual(found[b"PLTE"], bytes([0, 0, 0, 255, 255, 255]))

    def test_scaling_makes_each_dot_a_block(self):
        width, height, rows = paintings.scale(3, 2, self.ROWS, 2)
        self.assertEqual((width, height), (6, 4))
        self.assertEqual(rows, [bytes([0b11001100])] * 2 + [bytes([0b00110000])] * 2)

    def test_a_painting_is_recoloured_in_the_colourway(self):
        palette = theme.THEMES["rubedo"]
        found = chunks(paintings.render("dore-raven", palette.ink, palette.page, factor=2))
        self.assertEqual(found[b"PLTE"].hex(), palette.page[1:].lower() + palette.ink[1:].lower())
        width, height = struct.unpack(">II", found[b"IHDR"][:8])
        self.assertEqual((width, height), tuple(2 * n for n in paintings.bitmap("dore-raven")[:2]))

    def test_export_writes_a_named_png(self):
        with tempfile.TemporaryDirectory() as folder:
            path = paintings.export("smith-hermit", theme.THEMES["albedo"], Path(folder) / "out")
            self.assertEqual(path.name, "torrent-finder-smith-hermit-albedo.png")
            self.assertTrue(path.read_bytes().startswith(b"\x89PNG"))
            self.assertEqual(list(path.parent.iterdir()), [path])  # no temporary file left behind

    def test_a_spread_puts_the_faded_companion_left_and_the_plate_right(self):
        palette = theme.THEMES["citrinitas"]
        with patch.object(paintings, "bitmap", side_effect=lambda key: {
                "a": (2, 2, [bytes([0b11000000])] * 2), "b": (1, 2, [bytes([0b10000000])] * 2)}[key]):
            blob = paintings.spread("b", "a", palette.ink, palette.page, factor=1, aspect=3)
        found = chunks(blob)
        self.assertEqual(struct.unpack(">IIBB", found[b"IHDR"][:10]), (6, 2, 2, 3))  # 2-bit, palette, 3:1
        faint = paintings.faint(palette.ink, palette.page)
        self.assertEqual(found[b"PLTE"].hex(), (palette.page[1:] + palette.ink[1:] + faint[1:]).lower())
        rows = zlib.decompress(found[b"IDAT"])
        # Each row: a filter byte, then 6 pixels of 2 bits: companion (2) twice, page (0) three times, plate (1).
        self.assertEqual(rows, bytes([0, 0b10100000, 0b00010000]) * 2)
        self.assertEqual(paintings.faint("#3A3026", "#16120E", 1), "#3A3026")
        self.assertEqual(paintings.faint("#3A3026", "#16120E", 0), "#16120E")

    def test_the_facing_placement_exports_the_spread_under_its_own_name(self):
        palette = theme.THEMES["citrinitas"]
        with tempfile.TemporaryDirectory() as folder:
            path = paintings.export("flammarion", palette, folder, placement="facing")
            self.assertEqual(path.name, "torrent-finder-flammarion+smith-hermit-citrinitas.png")
            width, height = struct.unpack(">II", chunks(path.read_bytes())[b"IHDR"][:8])
            self.assertEqual(width, round(height * paintings.SPREAD_ASPECT))
            # Left and right share one picture: only the terminal's alignment differs.
            self.assertEqual(paintings.export("flammarion", palette, folder, placement="left").name,
                             "torrent-finder-flammarion-citrinitas.png")

    def test_placements_and_companions(self):
        self.assertEqual(list(paintings.PLACEMENTS), ["right", "left", "facing"])
        self.assertEqual(paintings.placement_key("left"), "left")
        self.assertIsNone(paintings.placement_key("middle"))
        for key in paintings.catalog():
            with self.subTest(key=key):
                companion = paintings.facing(key)
                self.assertIn(companion, paintings.catalog())
                self.assertNotEqual(companion, key)
                self.assertEqual(paintings.facing(companion), key)  # pairs face each other


class PaintingChoiceTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)
        theme.apply("citrinitas", focus="bar", density="comfortable")

    def capture(self) -> list:
        captured = []
        with patch("torrent_finder.ui.selector.arrow_select", side_effect=lambda items, **kw: captured.append(items)):
            appearance.appearance_menu()
        return captured[0]

    def downs_to(self, value) -> list:
        """The ↓ presses from the applied colourway's row to *value*'s (headings are skipped)."""
        items = self.capture()
        start = next(i for i, item in enumerate(items) if item.value == ("theme", theme.PALETTE.key))
        target = next(i for i, item in enumerate(items) if item.value == value)
        return [K.DOWN] * sum(item.enabled for item in items[start + 1:target + 1])

    def run_menu(self, keys):
        screen = Console(file=io.StringIO(), width=100, height=40, color_system=None)
        with patch.object(selector, "console", screen), \
             patch.object(selector, "_render", return_value=True), \
             patch.object(selector.sys, "stdout", io.StringIO()), \
             patch.object(selector.readchar, "readkey", side_effect=keys):
            appearance.appearance_menu()

    def test_athanor_lists_the_paintings_apart_from_the_colours(self):
        items = self.capture()
        labels = [item.label for item in items]
        self.assertIn("─── Painting ───", labels)
        rows = [item for item in items if isinstance(item.value, tuple) and item.value[0] == "painting"]
        self.assertEqual([row.value[1] for row in rows], [*paintings.catalog(), "none"])
        self.assertEqual(rows[0].marker, "●")  # the default painting
        self.assertIn("Paradise Lost", rows[0].description)
        self.assertIn(("export", None), [item.value for item in items])
        theme.apply("quiet")
        self.assertNotIn("─── Painting ───", [item.label for item in self.capture()])  # Simple has none

    def test_choosing_a_painting_keeps_the_colours_and_saves_both(self):
        self.run_menu(self.downs_to(("painting", "dore-raven")) + [K.ENTER, K.ESC])
        self.assertEqual(theme.PALETTE.key, "citrinitas")
        self.assertEqual(appearance.painting(), "dore-raven")
        self.assertEqual(appearance.saved()["painting"], "dore-raven")
        appearance.save("rubedo", "bar", "comfortable")  # a colour change keeps the painting
        self.assertEqual(appearance.saved()["painting"], "dore-raven")

    def test_saving_the_painting_as_an_image(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [p.unlink() for p in folder.iterdir()] and folder.rmdir())
        with patch.object(paintings, "export_folder", return_value=folder):
            self.run_menu(self.downs_to(("export", None)) + [K.ENTER, K.ESC])
        self.assertEqual([p.name for p in folder.iterdir()], ["torrent-finder-dore-satan-citrinitas.png"])
        self.assertIsNone(state.load_setting(appearance.SETTING))  # saving an image changes no setting

    def test_the_painting_side_is_chosen_beside_the_painting(self):
        items = self.capture()
        labels = [item.label for item in items]
        self.assertLess(labels.index("─── Painting ───"), labels.index("─── Painting side ───"))
        self.assertLess(labels.index("─── Painting side ───"), labels.index("─── Font ───") if "─── Font ───" in labels
                        else labels.index("─── Focus ───"))
        rows = [item for item in items if isinstance(item.value, tuple) and item.value[0] == "placement"]
        self.assertEqual([(row.label, row.value[1]) for row in rows],
                         [("Right", "right"), ("Left", "left"), ("Both sides", "facing")])
        self.assertEqual([row.marker for row in rows], ["●", "○", "○"])  # right is the default
        self.assertIn("Satan's despair", rows[2].description)  # the default painting's companion
        self.run_menu(self.downs_to(("placement", "facing")) + [K.ENTER, K.ESC])
        self.assertEqual(appearance.placement(), "facing")
        self.assertEqual(appearance.saved()["placement"], "facing")
        appearance.save("rubedo", "bar", "comfortable")  # a colour change keeps the side
        self.assertEqual(appearance.saved()["placement"], "facing")
        self.run_menu(self.downs_to(("painting", "none")) + [K.ENTER, K.ESC])
        self.assertNotIn("─── Painting side ───", [item.label for item in self.capture()])  # no painting, no side

    def test_settings_validate_and_back_up_the_painting(self):
        self.assertEqual(appearance.normalize({"painting": "none"})["painting"], "none")
        self.assertEqual(appearance.normalize({"painting": "mona-lisa"})["painting"], paintings.DEFAULT)
        self.assertEqual(appearance.normalize({"placement": "left"})["placement"], "left")
        self.assertEqual(appearance.normalize({"placement": "top"})["placement"], "right")
        settings_backup.validate_payload({"settings": {"appearance": {"theme": "rubedo", "painting": "flammarion",
                                                                      "placement": "facing"}}})
        with self.assertRaises(ValueError):
            settings_backup.validate_payload({"settings": {"appearance": {"painting": 7}}})


if __name__ == "__main__":
    unittest.main()
