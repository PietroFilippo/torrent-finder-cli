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
**required** — with none configured every call returns nothing and the provider
stays dormant.

Parsing is deliberately generic (anchors to nested library paths) because the
markup couldn't be pinned down without an account at development time; sizes
are best-effort. Madokami asks for gentle usage: this module only ever fetches
what the user explicitly picked — one search page, one directory listing, and
the chosen files — never crawls.
"""

import os
import re
import threading
from html import unescape
from urllib.parse import unquote, urlsplit

import requests

from torrent_finder.credentials import madokami_config

_BASE = "https://manga.madokami.al"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

_session: requests.Session | None = None
_session_lock = threading.Lock()

_ANCHOR_RE = re.compile(r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")

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
        if _session is None:
            cfg = madokami_config()
            if cfg:
                s = requests.Session()
                s.headers.update(_UA)
                s.auth = (cfg["username"], cfg["password"])
                _session = s
        return _session


def is_file_path(path: str) -> bool:
    """True when a library path points at an archive file (vs. a directory)."""
    return unquote(path).lower().endswith(_FILE_EXTS)


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


def search(query: str) -> list[dict]:
    """Search Madokami. Returns result dicts whose placeholder ``info_hash`` is
    the library path (prefixed, so it can't collide with real hashes). Empty
    list when no credentials are configured or on any error.

    Madokami is a file library, not a tracker — results carry no swarm stats or
    reliable sizes, and a pick is downloaded directly (see main.py's Madokami
    branch), not fed to the magnet pipeline.
    """
    session = _get_session()
    if session is None:
        return []
    try:
        r = session.get(f"{_BASE}/search", params={"q": query}, timeout=30)
        if r.status_code != 200:
            return []
        html = r.text
    except requests.RequestException:
        return []

    results: list[dict] = []
    for path, label in _content_paths(html):
        results.append({
            "name": label,
            "info_hash": f"madokami:{path}",  # placeholder; no torrent exists
            "seeders": "0",                   # no swarm — direct downloads
            "leechers": "0",
            "size": "0",                      # listing carries no reliable size
            "source": "Madokami",
            "page_url": _BASE + path,
            "mdk_path": path,                 # handle for listing/downloading
        })
    return results


def list_directory(path: str) -> list[dict] | None:
    """List a library directory. Returns ``{name, path, is_dir}`` dicts for its
    children (files first, page order otherwise preserved), or None on error /
    missing credentials.

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
    children: list[dict] = []
    for child, label in _content_paths(r.text):
        if not unquote(child).startswith(base):
            continue
        children.append({
            "name": label,
            "path": child,
            "is_dir": not is_file_path(child),
        })
    children.sort(key=lambda c: c["is_dir"])  # files first, stable within
    return children


class _Cancelled(Exception):
    """Internal: the caller's cancel_event fired mid-transfer."""


def download_file(path: str, dest_dir: str, cancel_event=None, progress_cb=None) -> str | None:
    """Stream one library file into ``dest_dir``; return the saved file path or
    None (failed or cancelled). The filename is the decoded last path segment.

    Volume archives run to hundreds of MB, so the transfer is observable and
    abortable mid-file: ``cancel_event`` is checked between chunks (the partial
    file is removed on abort), and ``progress_cb`` — when given — is called with
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
    dest = os.path.join(dest_dir, fname)
    try:
        with session.get(_BASE + path, timeout=60, stream=True) as resp:
            if resp.status_code != 200:
                return None
            try:
                total = int(resp.headers.get("Content-Length", "")) or None
            except ValueError:
                total = None
            done = 0
            if progress_cb:
                progress_cb(0, total)
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=65536):
                    if cancel_event is not None and cancel_event.is_set():
                        raise _Cancelled()
                    if chunk:
                        fh.write(chunk)
                        done += len(chunk)
                        if progress_cb:
                            progress_cb(done, total)
    except (_Cancelled, requests.RequestException, OSError):
        try:
            os.remove(dest)  # don't leave a truncated archive behind
        except OSError:
            pass
        return None
    return dest


def test_credentials(username: str, password: str) -> tuple[bool | None, str]:
    """Verify credentials with one authenticated request. Returns (ok, message):
    True accepted, False rejected, None couldn't reach Madokami."""
    try:
        r = requests.get(
            _BASE + "/", auth=(username, password), headers=_UA, timeout=25
        )
    except requests.RequestException as e:
        return None, f"Couldn't reach Madokami ({type(e).__name__})"
    if r.status_code in (401, 403):
        return False, "Login failed — check username/password"
    if r.status_code == 200:
        return True, "Login successful"
    return None, f"Unexpected response from Madokami (HTTP {r.status_code})"
