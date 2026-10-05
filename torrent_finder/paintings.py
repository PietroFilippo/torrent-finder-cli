"""Public-domain engravings the Athanor design shows behind the terminal.

Each painting is a two-tone dither stored as a 1-bit PNG (filter 0) in
``assets/paintings``, with its credits in ``catalog.json``; set bits are the
engraving's light parts. At run time a painting is recoloured into a
colourway's ink and page colours and scaled up by whole pixels, using only
``zlib`` and ``struct``. ``scripts/build_paintings.py`` makes the assets from
Wikimedia Commons scans. See docs/adr/0022-athanor-design.md.
"""

from __future__ import annotations

import json
import struct
import zlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets" / "paintings"
NONE = "none"
DEFAULT = "dore-satan"
_SIGNATURE = b"\x89PNG\r\n\x1a\n"


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


# --- 1-bit PNG ------------------------------------------------------------------------

def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def write_png(width: int, height: int, rows: list[bytes], colours: tuple[tuple, tuple]) -> bytes:
    """A 1-bit palette PNG: clear bits take ``colours[0]``, set bits ``colours[1]``."""
    header = struct.pack(">IIBBBBB", width, height, 1, 3, 0, 0, 0)
    palette = bytes(colours[0]) + bytes(colours[1])
    data = zlib.compress(b"".join(b"\x00" + row for row in rows), 9)
    return (_SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"PLTE", palette)
            + _chunk(b"IDAT", data) + _chunk(b"IEND", b""))


def read_png(blob: bytes) -> tuple[int, int, list[bytes]]:
    """Width, height and packed rows of a 1-bit PNG written with filter 0 (as ``write_png`` writes)."""
    if not blob.startswith(_SIGNATURE):
        raise ValueError("not a PNG")
    position, width, height, data = len(_SIGNATURE), 0, 0, b""
    while position < len(blob):
        length, kind = struct.unpack(">I4s", blob[position:position + 8])
        body = blob[position + 8:position + 8 + length]
        if kind == b"IHDR":
            width, height, depth, _colour, _comp, _filter, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 1 or interlace:
                raise ValueError("only non-interlaced 1-bit PNGs are supported")
        elif kind == b"IDAT":
            data += body
        position += 12 + length
    raw = zlib.decompress(data)
    stride = (width + 7) // 8
    rows = []
    for y in range(height):
        start = y * (stride + 1)
        if raw[start] != 0:
            raise ValueError("unexpected PNG filter")
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


def render(key: str, ink: str, page: str, factor: int = 2) -> bytes:
    """The painting as a PNG in *ink* on *page*, each dot *factor* pixels square."""
    width, height, rows = scale(*bitmap(key), factor)
    return write_png(width, height, rows, (_rgb(page), _rgb(ink)))


def export_folder() -> Path:
    """Where saved paintings go: the Pictures folder, or the home folder without one."""
    pictures = Path.home() / "Pictures"
    return pictures / "torrent-finder" if pictures.is_dir() else Path.home() / "torrent-finder"


def export(key: str, palette, folder: "str | Path", factor: int = 2) -> Path:
    """Save the painting in *palette*'s page and ink colours as a PNG in *folder*; returns its path."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"torrent-finder-{key}-{palette.key}.png"
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(render(key, palette.ink or palette.steel, palette.page, factor))
    temporary.replace(path)
    return path
