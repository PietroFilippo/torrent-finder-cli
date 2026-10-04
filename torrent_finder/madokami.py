"""Madokami search client — HTTP Basic auth + HTML scrape (no official API).

manga.madokami.al is a private manga library — a curated file archive, **not a
torrent tracker**. Everything (including ``/search``) sits behind HTTP Basic
auth, and releases are direct-download archives (zip/cbz/rar per volume or
chapter), so unlike every other source here there is no magnet and no
``.torrent``: a selection is downloaded straight to disk by this module.

The shape:

  1. search ``/search?q=<query>`` for library entries. A hit is a *path* — a
     series directory (usual case) or a single archive file. The path doubles
     as the placeholder ``info_hash`` so results dedupe cleanly,
  2. a picked directory is listed (``list_directory``) so the user can choose
     volumes, then each file is streamed to the download folder
     (``download_file``). Both reuse the same authenticated session.

Credentials come from ``credentials.py`` (env var or gitignored file) and are
**required** — searches report a missing or rejected login explicitly.

Parsing is deliberately generic (anchors to nested library paths) because the
markup couldn't be pinned down without an account at development time; sizes
are best-effort. Madokami asks for gentle usage: this module only ever fetches
what the user explicitly picked — one search page, one directory listing, and
the chosen files — never crawls.
"""

import os
import re
import threading
from collections import Counter
from html import unescape
from urllib.parse import unquote, urlsplit

import requests

from torrent_finder.direct_download import Cancelled, safe_filename, save_response
from torrent_finder.result_view import title_score
from torrent_finder.search_result import SearchResult
from torrent_finder.search_control import search_request

from torrent_finder.credentials import madokami_config

_BASE = "https://manga.madokami.al"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

_session: requests.Session | None = None
_session_lock = threading.Lock()

_ANCHOR_RE = re.compile(r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")
# A folder listing is a table: name link, then size ("48.2M", "-" for folders).
_ROW_RE = re.compile(r"<tr\b.*?</tr>", re.S)
_CELL_RE = re.compile(r"<td\b[^>]*>(.*?)</td>", re.S)
_SIZE_RE = re.compile(r"([\d.]+)\s*([KMGT]?)i?B?\Z", re.I)

# Areas outside the main A-Z manga index that hold a grouping folder of their
# own before the series: /Manga/_Autouploads/AutoUploaded from …/<series>.
_GROUPED_AREAS = {"_Autouploads": 2}

# Archive/file extensions Madokami serves — anything else is a directory.
_FILE_EXTS = (".zip", ".cbz", ".rar", ".cbr", ".7z", ".epub", ".pdf", ".mobi")

# App/nav paths that also show up as anchors but are never library content.
_SKIP_PREFIXES = (
    "/search", "/recent", "/stats", "/user", "/reader", "/login", "/logout",
    "/follows", "/random", "/css", "/js", "/img", "/static", "/favicon",
)


def _strip_tags(html: str) -> str:
    return unescape(_TAG_RE.sub("", html)).strip()


def _get_session() -> requests.Session | None:
    """Return a Basic-auth session (cached for the process), or None when no
    credentials are configured. Basic auth is stateless — no login round-trip;
    bad credentials just surface as 401s on the first real request."""
    global _session
    with _session_lock:
        cfg = madokami_config()
        auth = _basic_auth(cfg["username"], cfg["password"]) if cfg else None
        if _session is not None and _session.auth != auth:
            _session.close()
            _session = None
        if _session is None and auth:
            _session = requests.Session()
            _session.headers.update(_UA)
            _session.auth = auth
        return _session


def _basic_auth(username: str, password: str) -> tuple[bytes, bytes]:
    """Basic-auth credentials as UTF-8 bytes; requests would encode text as
    Latin-1 and fail on characters such as "€"."""
    return username.encode("utf-8"), password.encode("utf-8")


def is_file_path(path: str) -> bool:
    """True when a library path points at an archive file (vs. a directory)."""
    return unquote(path).lower().endswith(_FILE_EXTS)


def _is_index(levels) -> bool:
    """The A-Z index folders before a series: "O", "ON", "ONE_"."""
    first, second, third = levels
    return (len(first), len(second), len(third)) == (1, 2, 4) and not any(
        ch.islower() for ch in first + second + third
    ) and second.startswith(first) and third.startswith(second.rstrip("_"))


def describe(path: str) -> tuple[tuple[str, ...], str]:
    """A library path as (folders from the series down, area).

    "/Manga/O/ON/ONE_/One Piece/!One Piece [Viz]" → (("One Piece", "One Piece
    [Viz]"), ""). The area names anything outside the main manga index:
    "Raws", "Novels", "Doujinshi", "Oneshots", "Autouploads". Madokami's "!"
    prefix (sorts a folder first) is dropped.
    """
    parts = [unquote(part) for part in path.strip("/").split("/") if part]
    if not parts:
        return (), ""
    section, rest = parts[0], parts[1:]
    area = "" if section == "Manga" else section
    if len(rest) >= 3 and _is_index(rest[:3]):
        rest = rest[3:]
    elif rest and (rest[0].startswith("_") or rest[0] == "Oneshots"):
        area = rest[0].lstrip("_")
        rest = rest[_GROUPED_AREAS.get(rest[0], 1):]
    chain = tuple(part.lstrip("!").strip() or part for part in rest) or (parts[-1],)
    return chain, area


def display_name(path: str) -> str:
    """A result name that says what a pick opens:
    "One Piece [series folder]", "One Piece › One Piece [Viz] [folder]",
    "Berserk › Berserk v01.cbz [file]", "One Piece x Toriko [Oneshots · series folder]"."""
    chain, area = describe(path)
    shown = chain if len(chain) <= 3 else (chain[0], "…", chain[-2], chain[-1])
    kind = "file" if is_file_path(path) else "series folder" if len(chain) == 1 else "folder"
    return f"{' › '.join(shown)} [{' · '.join(filter(None, (area, kind)))}]"


def title_relevance(path: str, query: str) -> int:
    """How well a library path matches the searched title (0-3, like title_score).

    The series named exactly as searched, and everything inside it, rank first;
    a series whose title only starts with or contains the query comes after.
    Madokami also finds series through their other names and authors (One
    Piece finds "Soft Shell"); those rows rank last but stay listed.
    """
    chain, area = describe(path)
    if not chain:
        return 0
    series = title_score(chain[0], query)
    if series == 3 and not area:
        return 3
    own = title_score(chain[-1], query) if len(chain) > 1 else series
    return min(2, max(series, own))


def _size_bytes(text: str) -> int:
    """Bytes from a listing size such as "48.2M"; 0 when unknown ("-")."""
    match = _SIZE_RE.match(text.strip())
    if not match:
        return 0
    power = " KMGT".index((match.group(2) or " ").upper())
    return int(float(match.group(1)) * 1024 ** power)


def _content_paths(html: str) -> list[tuple[str, str]]:
    """Extract ``(path, label)`` library links from a page, in page order.

    Generic on purpose: any same-site anchor at least two segments deep that
    isn't an app/nav path is treated as content. Handles both relative and
    absolute hrefs; labels fall back to the decoded last path segment when the
    anchor wraps no usable text (e.g. an icon).
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for href, text in _ANCHOR_RE.findall(html):
        href = unescape(href)
        if href.startswith(("http://", "https://")):
            parts = urlsplit(href)
            if parts.netloc and parts.netloc not in urlsplit(_BASE).netloc:
                continue
            href = parts.path
        if not href.startswith("/") or href.startswith(_SKIP_PREFIXES):
            continue
        path = href.split("?")[0].split("#")[0].rstrip("/")
        if path.count("/") < 2 or path in seen:  # skip "/" and top-nav roots
            continue
        seen.add(path)
        label = _strip_tags(text) or unquote(path.rsplit("/", 1)[-1])
        out.append((path, label))
    return out


def search(query: str) -> list[SearchResult]:
    """Search Madokami. Returns SearchResult rows whose placeholder ``info_hash`` is
    the library path (prefixed, so it can't collide with real hashes). Empty
    list on network failure; missing/rejected credentials raise SearchError.

    Madokami is a file library, not a tracker — results carry no swarm stats or
    reliable sizes, and a pick is downloaded directly (see main.py's Madokami
    branch), not fed to the magnet pipeline.
    """
    session = _get_session()
    if session is None:
        from torrent_finder.search_errors import login_required
        raise login_required("Madokami")
    paths = _search_paths(session, query)
    # The site's search misses names typed with punctuation: "Mahjong Hishoden:
    # Naki no Ryuu" finds nothing, the same name without ":" finds the series.
    plain = " ".join(re.sub(r"[^\w\s'-]", " ", query).split())
    if not paths and plain and plain != query:
        paths = _search_paths(session, plain)
    results: list[SearchResult] = []
    for path in paths:
        results.append(SearchResult(
            name=display_name(path),
            info_hash=f"madokami:{path}",  # placeholder; no torrent exists
            seeders=0,                   # no swarm - direct downloads
            leechers=0,
            size=0,                      # listing carries no reliable size
            source="Madokami",
            page_url=_BASE + path,
            handle={"mdk_path": path},                 # handle for listing/downloading
        ))
    return results


def _search_paths(session, query: str) -> list[str]:
    """Library paths one search page lists; [] on network failure."""
    try:
        r = search_request(session.get, f"{_BASE}/search", params={"q": query}, timeout=30)
        if r.status_code in (401, 403):
            from torrent_finder.search_errors import SearchError
            raise SearchError("Madokami rejected the login. Check your saved credentials in Credentials.")
        if r.status_code != 200:
            return []
    except requests.RequestException:
        return []
    return [path for path, _label in _content_paths(r.text)]


def list_directory(path: str) -> list[dict] | None:
    """List a library directory. Returns ``{name, path, is_dir, size}`` dicts for
    its children (files first, page order otherwise preserved; ``size`` in bytes,
    0 when unknown), or None on error / missing credentials.

    Only direct children are returned — anchors whose decoded path nests under
    ``path``. No recursion: Madokami asks for gentle usage, and one level is
    what the volume picker needs.
    """
    session = _get_session()
    if session is None or not path:
        return None
    try:
        r = session.get(_BASE + path, timeout=30)
        if r.status_code != 200:
            return None
    except requests.RequestException:
        return None

    base = unquote(path).rstrip("/") + "/"
    sizes = _listing_sizes(r.text)
    children: list[dict] = []
    for child, label in _content_paths(r.text):
        if not unquote(child).startswith(base) or child.rsplit("/", 1)[-1] == "..":
            continue  # outside this folder, or the "Back" link to the parent
        is_dir = not is_file_path(child)
        children.append({
            "name": label.rstrip("/").lstrip("!") if is_dir else label,
            "path": child,
            "is_dir": is_dir,
            "size": 0 if is_dir else sizes.get(child, 0),
        })
    children.sort(key=lambda c: c["is_dir"])  # files first, stable within
    return children


def _listing_sizes(html: str) -> dict[str, int]:
    """Each listed path's size in bytes, from the listing table's size column."""
    sizes = {}
    for row in _ROW_RE.findall(html):
        cells = _CELL_RE.findall(row)
        link = _ANCHOR_RE.search(cells[0]) if len(cells) >= 2 else None
        if link:
            path = unescape(link.group(1)).split("?")[0].rstrip("/")
            sizes[path] = _size_bytes(_strip_tags(cells[1]))
    return sizes


def save_folder(file_path: str, download_dir: str) -> str:
    """The folder a library file is saved in when grouped, named after the
    library folders holding it: "Naki no Ryuu", "One Piece/One Piece [Viz]".
    Areas outside the main index are named too: "Naki no Ryuu [Raws]"."""
    chain, area = describe(file_path.rsplit("/", 1)[0])
    parts = [safe_filename(part, "Madokami") for part in chain]
    if area and parts:
        parts[0] = safe_filename(area if parts[0].lstrip("_") == area else f"{parts[0]} [{area}]")
    return os.path.join(download_dir, *parts)


def download_folders(paths, download_dir: str) -> dict:
    """Where each picked library file is saved. Files sharing a library folder
    with another picked file go into that folder (``save_folder``), and so does
    a file whose folder an earlier download created; a lone file goes straight
    into *download_dir*."""
    folders = {path: save_folder(path, download_dir) for path in paths}
    shared = Counter(folders.values())
    return {path: folder if shared[folder] > 1 or os.path.isdir(folder) else download_dir
            for path, folder in folders.items()}


def download_file(path: str, dest_dir: str, cancel_event=None, progress_cb=None) -> str | None:
    """Stream one library file into ``dest_dir``; return the saved file path or
    None (failed or cancelled). The filename is the decoded last path segment,
    numbered when that name is already taken (see ``direct_download``).

    Volume archives run to hundreds of MB, so the transfer is observable and
    abortable mid-file: ``cancel_event`` is checked between chunks, and
    ``progress_cb`` — when given — is called with
    ``(bytes_done, total_bytes_or_None)`` per chunk, the total coming from
    Content-Length when the server sends one.
    """
    session = _get_session()
    if session is None or not path:
        return None
    fname = unquote(path.rsplit("/", 1)[-1]) or "madokami-download"
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError:
        return None
    try:
        with session.get(_BASE + path, timeout=60, stream=True) as resp:
            if resp.status_code != 200:
                return None
            return save_response(resp, dest_dir, fname, cancel_event, progress_cb)
    except (Cancelled, requests.RequestException, OSError):
        return None


def test_credentials(username: str, password: str) -> tuple[bool | None, str]:
    """Verify credentials with one authenticated request. Returns (ok, message):
    True accepted, False rejected, None couldn't reach Madokami."""
    try:
        r = requests.get(
            _BASE + "/", auth=_basic_auth(username, password), headers=_UA, timeout=25
        )
    except requests.RequestException as e:
        return None, f"Couldn't reach Madokami ({type(e).__name__})"
    if r.status_code in (401, 403):
        return False, "Login failed — check username/password"
    if r.status_code == 200:
        return True, "Login successful"
    return None, f"Unexpected response from Madokami (HTTP {r.status_code})"
