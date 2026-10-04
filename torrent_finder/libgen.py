"""Library Genesis search client — anonymous HTML scrape + direct download.

Libgen is a public book library — direct-download files, **not a torrent
tracker**, and no login of any kind. The classic ``.is``/``.rs`` hosts are
dead; the live ``.li`` family mirrors share one layout and are tried in order.
Its JSON endpoint rejects search queries, so search scrapes the HTML table
(the same approach as ``fitgirl.py`` / ``madokami.py``).

The shape:

  1. search ``/index.php?req=<query>`` — one result row per file, carrying
     title/author/language/size/extension plus the file's md5 (the stable
     identity used as placeholder ``info_hash``),
  2. a picked result resolves ``/ads.php?md5=…`` to the keyed ``get.php``
     link, which redirects to a CDN and streams the file to disk.

Only what the user explicitly asked for is fetched — one search page, one
download page, and the chosen file. No crawling.
"""

import os
import re
from html import unescape
from urllib.parse import unquote

import requests

from torrent_finder.direct_download import Cancelled, save_response
from torrent_finder.search_result import SearchResult
from torrent_finder.search_control import search_request

_MIRRORS = ("https://libgen.li", "https://libgen.vg", "https://libgen.la")
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_MD5_RE = re.compile(r"ads\.php\?md5=([a-fA-F0-9]{32})")
# Anchored at href, not <a: the preceding tooltip attribute embeds literal
# "<br>" tags, which any [^>]* spanning the whole tag would trip over.
_TITLE_RE = re.compile(r'href="edition\.php[^"]*"[^>]*>(.*?)</a>', re.S)
_GET_LINK_RE = re.compile(r'href="(get\.php\?md5=[a-fA-F0-9]{32}[^"]*)"')
_TAG_RE = re.compile(r"<[^>]+>")
_FILENAME_RE = re.compile(r'filename="?([^";]+)"?', re.I)
# RFC 5987: filename*=UTF-8''Name%20with%20spaces.epub
_FILENAME_STAR_RE = re.compile(r"filename\*\s*=\s*([\w-]+)'[^']*'([^;\s]+)", re.I)

# Result-table column order on the .li family (9 cells per row).
_COL_AUTHOR, _COL_LANG, _COL_SIZE, _COL_EXT = 1, 4, 6, 7

_SIZE_UNITS = {"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4}


def _strip_tags(html: str) -> str:
    return " ".join(unescape(_TAG_RE.sub(" ", html)).split())


def parse_size(text: str) -> int:
    """Parse a Libgen size cell (e.g. '832 kB', '1.4 MB') into bytes."""
    m = re.match(r"([\d.,]+)\s*([a-zA-Z]+)", text.strip())
    if not m:
        return 0
    try:
        value = float(m.group(1).replace(",", "."))
    except ValueError:
        return 0
    return int(value * _SIZE_UNITS.get(m.group(2).lower(), 0))


def _parse_rows(html: str, mirror: str) -> list[SearchResult]:
    results: list[SearchResult] = []
    seen: set[str] = set()
    for row in _ROW_RE.findall(html):
        md5_match = _MD5_RE.search(row)
        if not md5_match:
            continue  # header/nav rows carry no file link
        md5 = md5_match.group(1).lower()
        if md5 in seen:
            continue
        cells = _CELL_RE.findall(row)
        if len(cells) < 8:
            continue

        title_match = _TITLE_RE.search(cells[0])
        title = _strip_tags(title_match.group(1) if title_match else cells[0])
        if not title:
            continue
        author = _strip_tags(cells[_COL_AUTHOR])
        language = _strip_tags(cells[_COL_LANG])
        extension = _strip_tags(cells[_COL_EXT]).lower()
        size_bytes = parse_size(_strip_tags(cells[_COL_SIZE]))

        # Extension/language ride in the name so filter presets (EPUB / PDF /
        # English…) bite on Libgen rows exactly like on torrent names.
        details = ", ".join(d for d in (extension, language) if d)
        name = title if not author else f"{title} — {author}"
        if details:
            name = f"{name} [{details}]"

        seen.add(md5)
        results.append(SearchResult(
            name=name,
            info_hash=f"libgen:{md5}",  # placeholder; no torrent exists
            seeders=0,                  # no swarm — direct downloads
            leechers=0,
            size=size_bytes,
            source="Libgen",
            page_url=f"{mirror}/ads.php?md5={md5}",
            handle={"lg_md5": md5},
            extra={"lg_ext": extension, "lg_author": author},
        ))
    return results


def search(query: str) -> list[SearchResult]:
    """Search Libgen across mirrors; first mirror yielding rows decides.

    A mirror that answers 200 but parses to zero rows does NOT settle the
    search — the .li host intermittently serves junk pages, so an empty
    answer falls through to the next mirror (a legit no-match query costs at
    most one request per mirror).

    Returns rows whose placeholder ``info_hash`` is the file md5 (prefixed so
    it can't collide with real hashes). A pick downloads the file directly
    (``LibgenAcquisition``), never the magnet pipeline. Empty list on error.
    """
    for mirror in _MIRRORS:
        try:
            r = search_request(requests.get,
                f"{mirror}/index.php",
                params={"req": query, "res": 100},
                headers=_UA,
                timeout=25,
            )
            if r.status_code != 200:
                continue
        except requests.RequestException:
            continue
        results = _parse_rows(r.text, mirror)
        if results:
            return results
    return []


def resolve_download_url(md5: str) -> str | None:
    """Resolve a file md5 to its keyed ``get.php`` URL, trying each mirror.

    The returned URL redirects to the serving CDN; ``requests`` follows it.
    None when every mirror fails or the page layout changed.
    """
    if not md5:
        return None
    for mirror in _MIRRORS:
        try:
            r = requests.get(
                f"{mirror}/ads.php", params={"md5": md5}, headers=_UA, timeout=25
            )
            if r.status_code != 200:
                continue
        except requests.RequestException:
            continue
        m = _GET_LINK_RE.search(r.text)
        if m:
            return f"{mirror}/{unescape(m.group(1))}"
    return None


def _disposition_name(header: str) -> str:
    """The file name a Content-Disposition header gives, or "".

    Prefers the RFC 5987 ``filename*`` form. A plain ``filename`` arrives
    decoded as Latin-1 by the HTTP library, so UTF-8 names are re-decoded."""
    star = _FILENAME_STAR_RE.search(header or "")
    if star:
        try:
            return unquote(star.group(2), encoding=star.group(1), errors="strict")
        except (LookupError, UnicodeDecodeError):
            pass
    plain = _FILENAME_RE.search(header or "")
    if not plain:
        return ""
    name = unescape(plain.group(1)).strip()
    try:
        return name.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "libgen-download"


def download_file(url: str, dest_dir: str, fallback_name: str,
                  cancel_event=None, progress_cb=None) -> str | None:
    """Stream one file into ``dest_dir``; return the saved path or None.

    The filename comes from the CDN's Content-Disposition when sent, else
    ``fallback_name``; it is numbered when already taken, since different books
    can share one (see ``direct_download``). Books are usually small but
    audio/scan files aren't: ``cancel_event`` is checked between chunks and
    ``progress_cb(bytes_done, total_or_None)`` runs per chunk.
    """
    if not url:
        return None
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError:
        return None
    try:
        with requests.get(url, headers=_UA, timeout=60, stream=True) as resp:
            if resp.status_code != 200:
                return None
            fname = os.path.basename(_disposition_name(resp.headers.get("Content-Disposition", "")))
            return save_response(resp, dest_dir, _safe_filename(fname or fallback_name),
                                 cancel_event, progress_cb)
    except (Cancelled, requests.RequestException, OSError):
        return None
