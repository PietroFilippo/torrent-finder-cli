"""Build the Athanor paintings: download public-domain engravings, dither them, store them.

    python scripts/build_paintings.py            # all of them
    python scripts/build_paintings.py dore-satan # one
    python scripts/build_paintings.py --credits  # only rewrite CREDITS.md

Needs Pillow and the network (a development tool; the app only reads the
results). Each scan comes from Wikimedia Commons, is turned to grey, its
contrast stretched, fitted into the size below and dithered (Floyd–Steinberg)
to two tones, light parts set; it is written as a 1-bit PNG with
``torrent_finder.paintings.write_png`` and its credits go into catalog.json.
"""

from __future__ import annotations

import io
import json
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
API = "https://commons.wikimedia.org/w/api.php"
AGENT = "torrent-finder-cli build_paintings (https://github.com/PietroFilippo/torrent-finder-cli)"

# key, title, artist, year, work, Commons file, gamma (above 1 darkens: keeps dark masses solid)
PAINTINGS = [
    ("dore-satan", "Satan in profile", "Gustave Doré", "1866", "Paradise Lost",
     "File:GustaveDoreParadiseLostSatanProfile.jpg", 1.5),
    ("dore-despair", "Satan's despair", "Gustave Doré", "1866", "Paradise Lost",
     "File:Gustave Dore Satan's Despair.jpg", 1.4),
    ("dore-quixote", "The windmills", "Gustave Doré", "1863", "Don Quixote",
     "File:Adventure with the Windmills.jpg", 1.4),
    ("dore-raven", "The Raven", "Gustave Doré", "1884", "The Raven",
     "File:Dore raven shadow2.jpg", 1.4),
    ("dore-charon", "Charon", "Gustave Doré", "1861", "Inferno",
     "File:Gustave Doré - Dante Alighieri - Inferno - Plate 9 (Canto III - Charon).jpg", 1.4),
    ("dore-mariner", "The ice was all around", "Gustave Doré", "1876", "The Rime of the Ancient Mariner",
     "File:Dore - the ice was all around.jpg", 1.3),
    ("durer-melencolia", "Melencolia I", "Albrecht Dürer", "1514", "",
     "File:Melencolia I MET DP815743.jpg", 1.4),
    ("flammarion", "The Flammarion engraving", "Unknown artist", "1888", "L'atmosphère",
     "File:Flammarion.jpg", 1.3),
    ("smith-hermit", "The Hermit", "Pamela Colman Smith", "1909", "Rider–Waite tarot",
     "File:RWS1909 - 09 Hermit.jpeg", 1.2),
    ("maier-emblem", "Emblem XXI", "Matthäus Merian, for Michael Maier", "1617", "Atalanta Fugiens",
     "File:Michael Maier Atalanta Fugiens Emblem 21.jpeg", 1.3),
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


def dither(image: Image.Image, gamma: float) -> Image.Image:
    grey = ImageOps.autocontrast(image.convert("L"), cutoff=1)
    scale = HEIGHT / grey.height
    width = min(MAX_WIDTH, round(grey.width * scale))
    grey = ImageOps.fit(grey, (width, HEIGHT), Image.LANCZOS) if width == MAX_WIDTH else \
        grey.resize((width, HEIGHT), Image.LANCZOS)
    grey = grey.point(lambda v: int(255 * (v / 255) ** gamma))
    return grey.convert("1", dither=Image.FLOYDSTEINBERG)


def main(keys: list[str]) -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    catalog_path = ASSETS / "catalog.json"
    existing = {e["key"]: e for e in json.loads(catalog_path.read_text(encoding="utf-8"))} \
        if catalog_path.exists() else {}
    for key, title, artist, year, work, commons, gamma in PAINTINGS:
        if keys and key not in keys:
            continue
        blob, page, licence = _scan(commons)
        if "public domain" not in licence.casefold() and not licence.upper().startswith(("PD", "CC0")):
            print(f"{key:18} skipped: the scan is {licence!r}, not public domain")
            continue
        image = dither(Image.open(io.BytesIO(blob)), gamma)
        rows = [image.tobytes()[y * ((image.width + 7) // 8):(y + 1) * ((image.width + 7) // 8)]
                for y in range(image.height)]
        file = f"{key}.png"
        (ASSETS / file).write_bytes(write_png(image.width, image.height, rows, ((0, 0, 0), (255, 255, 255))))
        existing[key] = {"key": key, "title": title, "artist": artist, "year": year, "work": work,
                         "source": page, "licence": "Public domain", "file": file}
        print(f"{key:18} {image.width}x{image.height}  {(ASSETS / file).stat().st_size // 1024} KB  {licence}")
        time.sleep(1)  # be gentle with Commons
    ordered = [existing[key] for key, *_ in PAINTINGS if key in existing]
    catalog_path.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_credits(ordered)


def write_credits(entries: list[dict]) -> None:
    lines = ["# The Athanor paintings", "",
             "Public-domain works, reduced to two tones by scripts/build_paintings.py from the",
             "Wikimedia Commons scans below. The app recolours them in the chosen colourway.", ""]
    for entry in entries:
        work = f", *{entry['work']}*" if entry["work"] else ""
        lines.append(f"- **{entry['title']}**: {entry['artist']}, {entry['year']}{work}. "
                     f"{entry['licence']}. <{entry['source']}>")
    (ASSETS / "CREDITS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1:] == ["--credits"]:
        write_credits(json.loads((ASSETS / "catalog.json").read_text(encoding="utf-8")))
    else:
        main(sys.argv[1:])
