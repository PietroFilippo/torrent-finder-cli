"""Text over the painting: every Athanor text role stays readable where the work block meets the plate.

The painting sits behind the right of the window (ADR-0031), and the
inspector pane reaches into its left side (ADR-0032). Contrast against the
bare page is not enough there: this measures each text-cell-sized patch of the
painting behind the pane in a 144x36 window (8x16 pixel cells), and requires
4.5:1 against the brightest tenth of them.
"""

import io
import unittest
import warnings

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirects saved settings before anything reads them
from PIL import Image

from torrent_finder import paintings
from torrent_finder.ui import theme

WIDTH, HEIGHT, CELL_W, CELL_H = 1152, 576, 8, 16
WORK = 107 * CELL_W  # where the main menu's pane ends at 144 columns
PAINTINGS = ("maier-emblem", "flammarion", "dore-satan")  # the densest plates near their left edge
ROLES = ("text", "steel", "accent", "sky", "good", "warn", "bad")


def _luminance(rgb) -> float:
    channels = [value / 255 for value in rgb]
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(a, b) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _rgb(colour: str) -> tuple:
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


def _behind_the_pane(palette) -> tuple:
    """The 90th-percentile brightest cell of the painting under the work block, over the given plates."""
    brightest = None
    for key in PAINTINGS:
        picture = Image.open(io.BytesIO(paintings.render(key, palette.ink, palette.page, 1, "right"))).convert("RGB")
        scale = HEIGHT / picture.height
        picture = picture.resize((round(picture.width * scale), HEIGHT), Image.BILINEAR)
        overlap = WORK - (WIDTH - picture.width)
        if overlap <= 0:
            continue
        cells = []
        for x in range(0, overlap - CELL_W + 1, CELL_W):
            for y in range(0, HEIGHT - CELL_H + 1, CELL_H):
                pixels = list(picture.crop((x, y, x + CELL_W, y + CELL_H)).getdata())
                cells.append(tuple(sum(p[i] for p in pixels) / len(pixels) for i in range(3)))
        cells.sort(key=_luminance)
        cell = cells[int(len(cells) * 0.9)]
        if brightest is None or _luminance(cell) > _luminance(brightest):
            brightest = cell
    return brightest


class PaintedContrastTests(unittest.TestCase):
    def test_every_text_role_reads_over_the_painting(self):
        for palette in theme.palettes("athanor"):
            behind = _behind_the_pane(palette)
            for role in ROLES:
                with self.subTest(colourway=palette.key, role=role):
                    self.assertGreaterEqual(round(_contrast(_rgb(getattr(palette, role)), behind), 1), 4.5)

    def test_muted_text_stays_quieter_than_body_text(self):
        for palette in theme.palettes("athanor"):
            with self.subTest(colourway=palette.key):
                page = _rgb(palette.page)
                self.assertLess(_contrast(_rgb(palette.steel), page), _contrast(_rgb(palette.text), page) * 0.7)


if __name__ == "__main__":
    unittest.main()
