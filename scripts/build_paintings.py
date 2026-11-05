"""Build the Athanor paintings: download public-domain engravings, dither them, store them.

    python scripts/build_paintings.py              # all of them
    python scripts/build_paintings.py dore-satan   # one
    python scripts/build_paintings.py --credits    # only rewrite CREDITS.md
    python scripts/build_paintings.py --out DIR    # write somewhere else, to compare

Needs Pillow and the network (a development tool; the app only reads the
results). Each scan comes from Wikimedia Commons. Its printed margins,
captions and borders are cropped away (the app dissolves a painting's edges
into the page, so a printed frame would read as a box); it is turned to grey,
its contrast stretched, fitted into the size below and reduced to two tones,
light parts set, with one of three dot screens: error diffusion (fine
engraving lines and architecture), grain (a stochastic screen, for soft tonal
plates) or lines (a horizontal line screen, for light subjects). It is
written as a 1-bit PNG with ``torrent_finder.paintings.write_png`` and its
credits go into catalog.json. Wide works (``wide``) fill the window behind
the text.
"""

from __future__ import annotations

import io
import json
import random
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageOps  # noqa: E402

from torrent_finder.paintings import ASSETS, write_png  # noqa: E402

HEIGHT, MAX_WIDTH = 560, 560  # dots; the app draws each dot as 2x2 pixels
WIDE_WIDTH = 980               # wide works: 1.75 times wider than tall, near a maximised window
API = "https://commons.wikimedia.org/w/api.php"
AGENT = "torrent-finder-cli build_paintings (https://github.com/PietroFilippo/torrent-finder-cli)"


def plate(key, title, artist, year, work, commons, gamma, *, crop=(0, 0, 0, 0), screen="diffusion",
          wide=False, focus=0.5, reach=None, invert=False):
    """One painting to build.

    *gamma* above 1 darkens (keeps dark masses solid). *crop* trims (left, top,
    right, bottom) fractions of the scan: printed margins, captions, borders.
    *screen* is ``diffusion``, ``grain`` or ``lines``. A *wide* work is cut to
    WIDE_WIDTH, *focus* placing the cut (0 keeps the top, 1 the bottom).
    *reach* overrides how far the side toward the text dissolves (a share of
    the width; see ``paintings.SIDE_FADE``), for a subject near that side.
    *invert* swaps light and dark first: an outline drawing on pale paper
    then glows on the page instead of lighting a solid block.
    """
    return dict(key=key, title=title, artist=artist, year=year, work=work, commons=commons, gamma=gamma,
                crop=crop, screen=screen, wide=wide, focus=focus, reach=reach, invert=invert)


PAINTINGS = [
    plate("dore-satan", "Satan in profile", "Gustave Doré", "1866", "Paradise Lost",
          "File:GustaveDoreParadiseLostSatanProfile.jpg", 1.5, screen="grain"),
    plate("dore-despair", "Satan's despair", "Gustave Doré", "1866", "Paradise Lost",
          "File:Gustave Dore Satan's Despair.jpg", 1.4, crop=(0.01, 0.01, 0.01, 0.01), screen="grain"),
    plate("dore-quixote", "The windmills", "Gustave Doré", "1863", "Don Quixote",
          "File:Adventure with the Windmills.jpg", 1.4, crop=(0.015, 0.01, 0.015, 0.015), screen="lines"),
    plate("dore-raven", "The Raven", "Gustave Doré", "1884", "The Raven",
          "File:Dore raven shadow2.jpg", 1.4, crop=(0.03, 0.025, 0.03, 0.05), screen="grain"),
    plate("dore-charon", "Charon", "Gustave Doré", "1861", "Inferno",
          "File:Gustave Doré - Dante Alighieri - Inferno - Plate 9 (Canto III - Charon).jpg", 1.4,
          crop=(0.025, 0.02, 0.025, 0.155)),
    plate("dore-mariner", "The ice was all around", "Gustave Doré", "1876", "The Rime of the Ancient Mariner",
          "File:Dore - the ice was all around.jpg", 1.3, crop=(0.02, 0.015, 0.02, 0.02), screen="grain"),
    plate("durer-melencolia", "Melencolia I", "Albrecht Dürer", "1514", "",
          "File:Melencolia I MET DP815743.jpg", 1.4, crop=(0.04, 0.035, 0.04, 0.05)),
    plate("maier-emblem", "Emblem XXI", "Matthäus Merian, for Michael Maier", "1617", "Atalanta Fugiens",
          "File:Michael Maier Atalanta Fugiens Emblem 21.jpeg", 1.3, crop=(0.02, 0.02, 0.02, 0.02)),
    plate("flammarion", "The Flammarion engraving", "Unknown artist", "1888", "L'atmosphère",
          "File:Flammarion.jpg", 1.3, crop=(0.065, 0.075, 0.055, 0.13)),
    plate("smith-hermit", "The Hermit", "Pamela Colman Smith", "1909", "Rider–Waite tarot",
          "File:RWS1909 - 09 Hermit.jpeg", 2.6, crop=(0.07, 0.08, 0.07, 0.14), reach=0.12, invert=True),
    # Wide works, in date order: they fill the window behind the text.
    plate("rembrandt-trees", "The Three Trees", "Rembrandt van Rijn", "1643", "",
          "File:Rembrandt van Rijn, The Three Trees, 1643, NGA 43418.jpg", 1.7,
          crop=(0.03, 0.035, 0.03, 0.04), wide=True),
    plate("friedrich-abbey", "The Abbey in the Oakwood", "Caspar David Friedrich", "1810", "",
          "File:Caspar David Friedrich - Abtei im Eichwald - Google Art Project.jpg", 1.2,
          crop=(0.005, 0.005, 0.005, 0.005), screen="grain", wide=True),
    plate("friedrich-ice", "The Sea of Ice", "Caspar David Friedrich", "1824", "",
          "File:Caspar David Friedrich - Das Eismeer - Hamburger Kunsthalle.jpg", 1.8,
          crop=(0.005, 0.005, 0.005, 0.005), wide=True),
    plate("martin-council", "Satan presiding at the Infernal Council", "John Martin", "1824", "Paradise Lost",
          "File:Martin, John - Satan presiding at the Infernal Council - 1824.JPG", 1.1,
          crop=(0.01, 0.01, 0.01, 0.01), wide=True, focus=0.3),
    plate("martin-deluge", "The Deluge", "John Martin", "1828", "",
          "File:John Martin - The Deluge - B1977.14.11938 - Yale Center for British Art.jpg", 1.2,
          crop=(0.079, 0.098, 0.079, 0.21), screen="grain", wide=True, focus=0.5),
    plate("martin-nineveh", "The Fall of Nineveh", "John Martin", "1829", "",
          "File:John Martin - The Fall of Ninevah - B1977.14.11939 - Yale Center for British Art.jpg", 1.1,
          crop=(0.05, 0.065, 0.051, 0.1), wide=True),
    plate("martin-pandemonium", "Pandemonium", "John Martin", "1831", "Paradise Lost",
          "File:John Martin - Pandemonium - B1977.14.11944 - Yale Center for British Art.jpg", 0.9,
          crop=(0.054, 0.054, 0.053, 0.11), wide=True, focus=0.45),
    plate("martin-seal", "The Opening of the Seventh Seal", "John Martin", "1837", "",
          "File:John Martin - The Opening of the Seventh Seal - B1978.43.931 - Yale Center for British Art.jpg", 1.2,
          crop=(0.071, 0.105, 0.07, 0.22), screen="grain", wide=True),
    plate("dore-london", "Over London by Rail", "Gustave Doré", "1872", "London: A Pilgrimage",
          "File:YCBA London a Pilgrimage 06 (cropped).jpg", 1.4,
          crop=(0.01, 0.01, 0.01, 0.01), wide=True, focus=0.4),
    plate("bocklin-isle", "Isle of the Dead", "Arnold Böcklin", "1880", "",
          "File:Böcklin - Die Toteninsel (Erste Fassung), GKS588, Kunstmuseum Basel.jpg", 1.2,
          crop=(0.005, 0.005, 0.005, 0.005), screen="grain", wide=True),
]


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _scan(title: str) -> tuple[bytes, str, str]:
    """The scan's bytes (a 1400-pixel rendition), its page URL and licence."""
    query = urllib.parse.urlencode({"action": "query", "format": "json", "prop": "imageinfo",
                                    "iiprop": "url|extmetadata", "iiurlwidth": 1400, "titles": title})
    pages = json.loads(_get(f"{API}?{query}"))["query"]["pages"]
    info = next(iter(pages.values()))["imageinfo"][0]
    licence = info.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "")
    return _get(info.get("thumburl") or info["url"]), info["descriptionurl"], licence


def dither(image: Image.Image, gamma: float, *, crop=(0, 0, 0, 0), screen="diffusion",
           wide=False, focus=0.5, invert=False) -> Image.Image:
    grey = image.convert("L")
    if invert:
        grey = ImageOps.invert(grey)
    left, top, right, bottom = crop
    grey = grey.crop((round(grey.width * left), round(grey.height * top),
                      round(grey.width * (1 - right)), round(grey.height * (1 - bottom))))
    grey = ImageOps.autocontrast(grey, cutoff=1)
    limit = WIDE_WIDTH if wide else MAX_WIDTH
    width = min(limit, round(grey.width * HEIGHT / grey.height))
    if width == limit:  # wider than its frame: keep the middle; for a wide work, *focus* picks the band
        grey = ImageOps.fit(grey, (limit, HEIGHT), Image.LANCZOS, centering=(0.5, focus))
    else:
        grey = grey.resize((width, HEIGHT), Image.LANCZOS)
    grey = grey.point(lambda v: int(255 * (v / 255) ** gamma))
    if screen == "grain":
        return _grain(grey)
    if screen == "lines":
        return _lines(grey)
    return grey.convert("1", dither=Image.FLOYDSTEINBERG)


def _grain(grey: Image.Image, seed: int = 7, spread: float = 0.35) -> Image.Image:
    """A stochastic screen: each dot meets a random threshold and half of its error
    passes on (Floyd–Steinberg weights), so shapes hold and the grain stays visible."""
    noise = random.Random(seed)
    width, height = grey.size
    tones, out = grey.load(), Image.new("1", grey.size)
    dots = out.load()
    here, below = [0.0] * (width + 2), [0.0] * (width + 2)
    for y in range(height):
        for x in range(width):
            value = tones[x, y] + here[x + 1]
            lit = value > 128 + (noise.random() - 0.5) * 255 * spread
            dots[x, y] = 1 if lit else 0
            error = (value - (255 if lit else 0)) / 2
            here[x + 2] += error * 7 / 16
            below[x] += error * 3 / 16
            below[x + 1] += error * 5 / 16
            below[x + 2] += error / 16
        here, below = below, [0.0] * (width + 2)
    return out


def _lines(grey: Image.Image, period: int = 4) -> Image.Image:
    """A horizontal line screen: each band of *period* rows lights from its middle
    outward as the tone rises; a little jitter keeps long edges from stepping."""
    width, height = grey.size
    tones, out = grey.load(), Image.new("1", grey.size)
    dots = out.load()
    middle = (period - 1) / 2
    for y in range(height):
        reach = abs(y % period - middle) / middle
        for x in range(width):
            jitter = ((x * 7 + y * 13) % 5 - 2) * 6
            dots[x, y] = 1 if tones[x, y] + jitter > 40 + reach * 190 else 0
    return out


def main(keys: list[str], out: Path = ASSETS) -> None:
    out.mkdir(parents=True, exist_ok=True)
    catalog_path = out / "catalog.json"
    if not catalog_path.exists() and (ASSETS / "catalog.json").exists():
        catalog_path.write_text((ASSETS / "catalog.json").read_text(encoding="utf-8"), encoding="utf-8")
    existing = {e["key"]: e for e in json.loads(catalog_path.read_text(encoding="utf-8"))} \
        if catalog_path.exists() else {}
    for spec in PAINTINGS:
        key = spec["key"]
        if keys and key not in keys:
            continue
        blob, page, licence = _scan(spec["commons"])
        if "public domain" not in licence.casefold() and not licence.upper().startswith(("PD", "CC0")):
            print(f"{key:18} skipped: the scan is {licence!r}, not public domain")
            continue
        image = dither(Image.open(io.BytesIO(blob)), spec["gamma"], crop=spec["crop"], screen=spec["screen"],
                       wide=spec["wide"], focus=spec["focus"], invert=spec["invert"])
        stride = (image.width + 7) // 8
        packed = image.tobytes()
        rows = [packed[y * stride:(y + 1) * stride] for y in range(image.height)]
        file = f"{key}.png"
        (out / file).write_bytes(write_png(image.width, image.height, rows, ((0, 0, 0), (255, 255, 255))))
        existing[key] = {"key": key, "title": spec["title"], "artist": spec["artist"], "year": spec["year"],
                         "work": spec["work"], "source": page, "licence": "Public domain", "file": file}
        if spec["wide"]:
            existing[key]["wide"] = True
        if spec["reach"] is not None:
            existing[key]["reach"] = spec["reach"]
        print(f"{key:18} {image.width}x{image.height}  {(out / file).stat().st_size // 1024} KB  {licence}")
        time.sleep(1)  # be gentle with Commons
    ordered = [existing[spec["key"]] for spec in PAINTINGS if spec["key"] in existing]
    catalog_path.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_credits(ordered, out)


def write_credits(entries: list[dict], out: Path = ASSETS) -> None:
    lines = ["# The Athanor paintings", "",
             "Public-domain works, cropped to the picture and reduced to two tones by",
             "scripts/build_paintings.py from the Wikimedia Commons scans below. The app",
             "recolours them in the chosen colourway.", ""]
    for entry in entries:
        work = f", *{entry['work']}*" if entry["work"] else ""
        lines.append(f"- **{entry['title']}**: {entry['artist']}, {entry['year']}{work}. "
                     f"{entry['licence']}. <{entry['source']}>")
    (out / "CREDITS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if arguments == ["--credits"]:
        write_credits(json.loads((ASSETS / "catalog.json").read_text(encoding="utf-8")))
    else:
        target = ASSETS
        if "--out" in arguments:
            index = arguments.index("--out")
            target = Path(arguments[index + 1])
            del arguments[index:index + 2]
        main(arguments, target)
