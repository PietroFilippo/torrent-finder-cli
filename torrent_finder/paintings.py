"""Public-domain engravings the Athanor design shows behind the terminal.

Each painting is a two-tone dither stored as a 1-bit PNG (filter 0) in
``assets/paintings``, with its credits in ``catalog.json``; set bits are the
engraving's light parts. At run time a painting is recoloured into a
colourway's ink and page colours and scaled up by whole pixels, using only
``zlib`` and ``struct``. ``scripts/build_paintings.py`` makes the assets from
Wikimedia Commons scans. See docs/adr/0022-athanor-design.md.
"""

# i18n: converted

from __future__ import annotations

import json
import struct
import zlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from torrent_finder.i18n import N_, t

ASSETS = Path(__file__).resolve().parent / "assets" / "paintings"
NONE = "none"
DEFAULT = "dore-satan"
_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Where the terminal puts the painting: the right of the window (the plate
# facing a page of text), the left (behind the menus), or both sides, with a
# companion plate faded toward the page on the left.
PLACEMENTS = {"right": N_("Right"), "left": N_("Left"), "facing": N_("Both sides")}
DEFAULT_PLACEMENT = "right"
# Companion plates for "both sides": the same book or the same mood.
_PAIRS = (("dore-satan", "dore-despair"), ("dore-charon", "dore-raven"), ("dore-quixote", "dore-mariner"),
          ("durer-melencolia", "maier-emblem"), ("flammarion", "smith-hermit"))
FACING = {a: b for pair in _PAIRS for a, b in (pair, pair[::-1])}
SPREAD_ASPECT = 1.9  # a maximised Windows Terminal window, tab row taken, on a 16:9 screen
FAINT = 0.65         # how much of the ink the faded companion keeps

# Mark the displayed catalogue text for extraction without changing the source
# records, their titles, or the keys used by settings and exported file names.
_TITLES = {title: title for title in (
    N_("Satan in profile", ctx="painting"), N_("Satan's despair", ctx="painting"),
    N_("The windmills", ctx="painting"), N_("The Raven", ctx="painting"),
    N_("Charon", ctx="painting"), N_("The ice was all around", ctx="painting"),
    N_("Melencolia I", ctx="painting"), N_("The Flammarion engraving", ctx="painting"),
    N_("The Hermit", ctx="painting"), N_("Emblem XXI", ctx="painting"),
)}
_WORKS = {work: work for work in (
    N_("Paradise Lost", ctx="painting work"), N_("Don Quixote", ctx="painting work"),
    N_("The Raven", ctx="painting work"), N_("Inferno", ctx="painting work"),
    N_("The Rime of the Ancient Mariner", ctx="painting work"),
    N_("L'atmosphère", ctx="painting work"), N_("Rider–Waite tarot", ctx="painting work"),
    N_("Atalanta Fugiens", ctx="painting work"),
)}


@dataclass(frozen=True)
class Painting:
    key: str
    title: str
    artist: str
    year: str
    work: str      # the book or series it illustrates
    source: str    # where the scan came from
    licence: str
    file: str

    @property
    def credit(self) -> str:
        return f"{self.artist}, {self.year}" + (f" ({self.work})" if self.work else "")

    def title_label(self) -> str:
        """The title at draw time; the catalogue's English title remains intact."""
        marked = _TITLES.get(self.title)
        return t(marked) if marked is not None else self.title

    def artist_credit_label(self) -> str:
        artist = self.artist
        if artist == "Unknown artist":  # i18n: ignore -- catalogue identity
            artist = t("Unknown artist")
        elif artist == "Matthäus Merian, for Michael Maier":  # i18n: ignore -- catalogue identity
            artist = t("{artist}, for {author}", artist="Matthäus Merian", author="Michael Maier")  # i18n: ignore -- names
        return f"{artist}, {self.year}"

    def credit_label(self) -> str:
        """Localised credit without changing the public English credit property."""
        marked = _WORKS.get(self.work)
        work = t(marked) if marked is not None else self.work
        return self.artist_credit_label() + (f" ({work})" if work else "")


@lru_cache(maxsize=1)
def catalog() -> dict[str, Painting]:
    """Every painting by key, in display order; empty when the assets are missing."""
    try:
        entries = json.loads((ASSETS / "catalog.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {entry["key"]: Painting(**entry) for entry in entries}


def painting_key(name: object) -> str | None:
    """A known painting key, ``none``, or None for anything else."""
    if name == NONE:
        return NONE
    return name if isinstance(name, str) and name in catalog() else None


def placement_key(name: object) -> str | None:
    """A known placement, or None for anything else."""
    return name if isinstance(name, str) and name in PLACEMENTS else None


def facing(key: str) -> str:
    """The companion plate shown faded beside *key* with the "both sides" placement."""
    companion = FACING.get(key)
    if companion in catalog():
        return companion
    others = [other for other in catalog() if other != key]
    return others[0] if others else key


# --- 1-bit PNG ------------------------------------------------------------------------

def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def write_png(width: int, height: int, rows: list[bytes], colours: tuple, depth: int = 1) -> bytes:
    """A palette PNG of *depth* bits per pixel (1 or 2): pixel value *n* takes ``colours[n]``."""
    header = struct.pack(">IIBBBBB", width, height, depth, 3, 0, 0, 0)
    palette = b"".join(bytes(colour) for colour in colours)
    data = zlib.compress(b"".join(b"\x00" + row for row in rows), 9)
    return (_SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"PLTE", palette)
            + _chunk(b"IDAT", data) + _chunk(b"IEND", b""))


def read_png(blob: bytes) -> tuple[int, int, list[bytes]]:
    """Width, height and packed rows of a 1-bit PNG written with filter 0 (as ``write_png`` writes)."""
    if not blob.startswith(_SIGNATURE):
        raise ValueError(t("not a PNG"))
    position, width, height, data = len(_SIGNATURE), 0, 0, b""
    while position < len(blob):
        length, kind = struct.unpack(">I4s", blob[position:position + 8])
        body = blob[position + 8:position + 8 + length]
        if kind == b"IHDR":
            width, height, depth, _colour, _comp, _filter, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 1 or interlace:
                raise ValueError(t("only non-interlaced 1-bit PNGs are supported"))
        elif kind == b"IDAT":
            data += body
        position += 12 + length
    raw = zlib.decompress(data)
    stride = (width + 7) // 8
    rows = []
    for y in range(height):
        start = y * (stride + 1)
        if raw[start] != 0:
            raise ValueError(t("unexpected PNG filter"))
        rows.append(raw[start + 1:start + 1 + stride])
    return width, height, rows


def scale(width: int, height: int, rows: list[bytes], factor: int) -> tuple[int, int, list[bytes]]:
    """Each pixel becomes a *factor* × *factor* block."""
    if factor <= 1:
        return width, height, rows
    out = []
    for row in rows:
        bits = "".join(f"{byte:08b}" for byte in row)[:width]
        wide = "".join(bit * factor for bit in bits)
        wide += "0" * (-len(wide) % 8)
        packed = int(wide, 2).to_bytes(len(wide) // 8, "big") if wide else b""
        out += [packed] * factor
    return width * factor, height * factor, out


def _rgb(colour: str) -> tuple[int, int, int]:
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))


@lru_cache(maxsize=16)
def bitmap(key: str) -> tuple[int, int, list[bytes]]:
    painting = catalog()[key]
    return read_png((ASSETS / painting.file).read_bytes())


def render(key: str, ink: str, page: str, factor: int = 2, placement: str = DEFAULT_PLACEMENT) -> bytes:
    """The painting as a PNG in *ink* on *page*, each dot *factor* pixels square.

    With the ``facing`` placement the picture is a spread: the companion plate,
    faded, on the left and *key* on the right (see ``spread``).
    """
    if placement == "facing":
        return spread(key, facing(key), ink, page, factor)
    width, height, rows = scale(*bitmap(key), factor)
    return write_png(width, height, rows, (_rgb(page), _rgb(ink)))


def faint(ink: str, page: str, keep: float = FAINT) -> str:
    """*ink* moved toward *page*: keep=1 is the ink itself, 0 the page."""
    a, b = _rgb(ink), _rgb(page)
    return "#%02X%02X%02X" % tuple(round(b[i] + (a[i] - b[i]) * keep) for i in range(3))


def _bit_rows(width: int, rows: list[bytes]) -> list[str]:
    return ["".join(f"{byte:08b}" for byte in row)[:width] for row in rows]


_LEFT_PLATE = str.maketrans({"0": "00", "1": "10"})   # pixel value 2: the faded ink
_RIGHT_PLATE = str.maketrans({"0": "00", "1": "01"})  # pixel value 1: the ink


def spread(key: str, companion: str, ink: str, page: str, factor: int = 2, aspect: float = SPREAD_ASPECT) -> bytes:
    """Two plates in one picture, *companion* faded on the left and *key* on the right, as a 2-bit PNG.

    Both stand at full height on the outer edges with the page between them, in
    a picture *aspect* times wider than tall (or just wide enough for both), so
    a terminal that fits it to the window's width keeps each plate at its edge.
    """
    left_w, left_h, left_rows = scale(*bitmap(companion), factor)
    right_w, right_h, right_rows = scale(*bitmap(key), factor)
    height = max(left_h, right_h)
    width = max(left_w + right_w, round(height * aspect))
    gap = "00" * (width - left_w - right_w)
    left, right = _bit_rows(left_w, left_rows), _bit_rows(right_w, right_rows)
    left_top, right_top = (height - left_h) // 2, (height - right_h) // 2
    rows = []
    for y in range(height):
        a = left[y - left_top] if 0 <= y - left_top < left_h else "0" * left_w
        b = right[y - right_top] if 0 <= y - right_top < right_h else "0" * right_w
        bits = a.translate(_LEFT_PLATE) + gap + b.translate(_RIGHT_PLATE)
        bits += "0" * (-len(bits) % 8)
        rows.append(int(bits, 2).to_bytes(len(bits) // 8, "big"))
    return write_png(width, height, rows, (_rgb(page), _rgb(ink), _rgb(faint(ink, page))), depth=2)


def export_folder() -> Path:
    """Where saved paintings go: the Pictures folder, or the home folder without one."""
    pictures = Path.home() / "Pictures"  # i18n: ignore -- directory name
    return pictures / "torrent-finder" if pictures.is_dir() else Path.home() / "torrent-finder"


def export(key: str, palette, folder: "str | Path", factor: int = 2, placement: str = DEFAULT_PLACEMENT) -> Path:
    """Save the painting in *palette*'s page and ink colours as a PNG in *folder*; returns its path.

    The ``facing`` placement saves the spread under its own name; the others
    share one picture, since only the terminal's alignment differs.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    look = f"{key}+{facing(key)}" if placement == "facing" else key
    path = folder / f"torrent-finder-{look}-{palette.key}.png"
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(render(key, palette.ink or palette.steel, palette.page, factor, placement))
    temporary.replace(path)
    return path
