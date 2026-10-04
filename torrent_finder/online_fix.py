"""Online-Fix.me search client — login + HTML scrape (no official API).

online-fix.me hosts "online fixes" — co-op / multiplayer cracks (Steam emulators
like Goldberg / OnlineFix) bundled with games. Like RuTracker it needs a login to
reach downloads, and it never exposes a public magnet: games are distributed as
**.torrent files on online-fix's own (private) tracker**, plus password-protected
multi-part archives (the archive password is always ``online-fix.me``).

So this module mirrors ``rutracker.py`` in shape but stops one step short of a
magnet, because there is no public info hash to feed the existing download
pipeline:

  1. scrape the public DLE search listing for game posts (title + post URL) with
     no login, using the numeric post id as a placeholder ``info_hash`` so a
     search costs a single request,
  2. resolve and download a post's ``.torrent`` — also without login: the post
     page is public and online-fix's uploads host gates files by HTTP *referer*
     (hotlink protection), not auth, so we just send the site referer,
  3. (optional) log in for the credentials menu / future needs, via online-fix's
     JS ``authtoken`` DataLife Engine flow.

Credentials are optional — search and ``.torrent`` download both work
anonymously. This is HTML scraping (and behind Cloudflare), so it is inherently
fragile: an online-fix.me layout change will need updates here. The selectors
below are best-effort.
"""

import os
import re
import threading
import time
from contextlib import contextmanager
from html import unescape
from urllib.parse import urljoin, unquote

import requests

from torrent_finder.search_errors import SearchError
from torrent_finder.search_result import SearchResult
from torrent_finder.search_control import SearchInterrupted, search_request, search_stopped, search_wait
from torrent_finder.result_view import matches_name

_BASE = "https://online-fix.me"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
# The uploads host gates files by HTTP referer (hotlink protection), not login —
# sending the site's own referer is enough to list a directory or fetch a .torrent.
_REFERER = {"Referer": _BASE + "/"}

# The single archive password online-fix.me uses for every release. Surfaced to
# the user on select and consumed by the (future) post-download unpack step.
ARCHIVE_PASSWORD = "online-fix.me"

# Search and download are anonymous, so we cache one anonymous session. Login is
# only used to verify credentials in the menu (see _do_login / test_credentials).
_anon_session: requests.Session | None = None
_session_lock = threading.Lock()

# Game post links look like /games/<category>/<id>-<slug>.html — stable across
# the theme, so we key the scrape on this rather than guessing CSS class names.
_GAME_HREF_RE = re.compile(
    r'href="(?:https?://online-fix\.me)?(/games/[a-z0-9_-]+/(\d+)-[^"]+\.html)"',
    re.I,
)
_TORRENT_HREF_RE = re.compile(r'href="([^"]+\.torrent[^"]*)"', re.I)
# online-fix links a per-game directory on its uploads host, not the .torrent
# file directly; the file lives inside it.
_TORRENT_DIR_RE = re.compile(
    r'href="(https?://[^"]*uploads\.online-fix\.me[^"]*/torrents/[^"]+)"', re.I)
_ALT_ATTR_RE = re.compile(r'\salt="([^"]+)"')      # cover image alt = clean title
_TITLE_ATTR_RE = re.compile(r'title="([^"]+)"')
_H2_TITLE_RE = re.compile(r'<h2 class="title">(.*?)</h2>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")

# The search page lists each hit in a "news news-search" block. Every page also
# carries a sidebar of popular games (horizontal slider), so scanning the whole
# page can turn a sidebar link into a "result", e.g. on a cooldown page.
_RESULT_BLOCK_RE = re.compile(r'<div class="news news-search"')
_RESULTS_END_RE = re.compile(r'class="horizontal-slider"|<aside')
# Rendered on every search page, including ones with no results; absent from
# cooldown and error pages.
_SEARCH_FORM = 'id="fullsearch"'
# DLE flood control: "Вы сможете воспользоваться поиском через 10 секунд."
_COOLDOWN_RE = re.compile(r"(?:поиском|search)[^<]{0,60}?(\d+)\s*(?:секунд|second)", re.I)

# The site refuses searches closer together than this (per session). Both game
# providers search it, so searches go through one gate: spaced out, and an
# identical query within _REUSE_SECONDS reuses the rows instead of asking again.
_SEARCH_INTERVAL = 10.0
_REUSE_SECONDS = 30.0
_search_gate = threading.Lock()
_last_search = 0.0  # time.monotonic() of the latest search request
_recent: dict[str, tuple[float, list]] = {}


def _strip_tags(html: str) -> str:
    return unescape(_TAG_RE.sub("", html)).strip()


def _deslug(path: str) -> str:
    """Fallback title from the URL slug (…/123-dayz-po-seti.html → 'Dayz Po Seti').

    Used when a search anchor wraps only a thumbnail and carries no usable text.
    """
    m = re.search(r"/\d+-([^/]+)\.html$", path)
    if not m:
        return "Unknown"
    return unescape(m.group(1).replace("-", " ")).strip().title() or "Unknown"


def _logged_in(session: requests.Session) -> bool:
    """DLE marks an authenticated session with a numeric ``dle_user_id`` cookie."""
    uid = session.cookies.get("dle_user_id")
    return bool(uid and uid not in ("", "deleted"))


def _do_login(session: requests.Session, username: str, password: str) -> None:
    """Run the online-fix.me login on ``session`` (cookies land in its jar).

    The theme logs in via JS (``dologin()``), not a plain form POST: it first
    GETs ``engine/ajax/authtoken.php`` for a one-shot anti-bot token, appends it
    to the login form as a hidden field, then submits to ``/``. We replicate that
    exactly — GET homepage (session cookies) → GET authtoken → POST the form with
    ``login_name`` / ``login_password`` / ``login=submit`` plus the token field.
    Without the token DLE silently refuses the login. UTF-8 throughout (unlike
    RuTracker's cp1251). Raises ``requests.RequestException`` on a network error.
    """
    session.get(_BASE + "/", timeout=25)
    data = {"login_name": username, "login_password": password, "login": "submit"}
    try:
        tok = session.get(
            _BASE + "/engine/ajax/authtoken.php",
            headers={"X-Requested-With": "XMLHttpRequest", "Referer": _BASE + "/"},
            timeout=20,
        ).json()
        if tok.get("field"):
            data[tok["field"]] = tok.get("value", "")
    except (requests.RequestException, ValueError):
        # No token → login will fail; surfaced to the user as a normal
        # verification failure rather than a crash.
        pass
    session.post(
        _BASE + "/",
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": _BASE + "/",
        },
        timeout=25,
    )


def _anon_http() -> requests.Session:
    """Cached anonymous session for public reads (search). Visits the homepage
    once so PHPSESSID / Cloudflare cookies are in the jar."""
    global _anon_session
    with _session_lock:
        if _anon_session is None:
            s = requests.Session()
            s.headers.update(_UA)
            try:
                search_request(s.get, _BASE + "/", timeout=25)
            except requests.RequestException:
                pass
            _anon_session = s
        return _anon_session


def search(query: str) -> list[SearchResult]:
    """Search online-fix.me. Returns SearchResult rows with the post id as a
    placeholder ``info_hash`` (the real ``.torrent`` is resolved on select via
    ``resolve_torrent``). Search and download are public — no login needed.
    Empty list on network failure.

    Raises ``SearchError`` (shown as a retryable failure, not as "no results")
    for a cooldown that doesn't fit in the search's remaining time, an HTTP
    error, or a page that is neither results nor a search page.

    Results carry no seeders / size — the DLE listing exposes neither, so those
    are zero-filled and the table just won't differentiate on them.
    """
    key = " ".join(query.casefold().split())
    with _one_search_at_a_time():
        reused = _recent.get(key)
        if reused and time.monotonic() - reused[0] < _REUSE_SECONDS:
            return list(reused[1])
        html = _search_page(query)
        if html is None:
            return []
        rows = _parse_results(html, query)
        _recent[key] = (time.monotonic(), rows)
        return list(rows)


def empty_search_hint(query: str) -> str:
    """Advice when a multi-word title finds nothing: the site matches title text
    literally, so punctuation or extra words can hide a game it has."""
    if len(query.split()) < 2:
        return ""
    return ("Online-Fix matches title text literally: try one distinctive word "
            "(e.g. Starve for Don't Starve Together).")


@contextmanager
def _one_search_at_a_time():
    """Hold the search gate; waiting for it ends early if the search stops."""
    while not _search_gate.acquire(timeout=0.1):
        if search_stopped():
            raise SearchInterrupted()
    try:
        yield
    finally:
        _search_gate.release()


def _cooldown_seconds(html: str) -> int | None:
    """Seconds the site asks to wait before searching again, or None."""
    if _RESULT_BLOCK_RE.search(html):
        return None
    match = _COOLDOWN_RE.search(html)
    return int(match.group(1)) if match else None


def _search_page(query: str) -> str | None:
    """The search page's HTML, paced and retried once after a cooldown; None on network failure."""
    global _last_search
    wait = _SEARCH_INTERVAL - (time.monotonic() - _last_search)
    for _attempt in range(2):
        if wait > 0 and not search_wait(wait):
            raise SearchError(f"Online-Fix allows one search every {_SEARCH_INTERVAL:.0f} seconds and "
                              "this one ran out of time waiting. Press r to retry.")
        # The site's search form is a GET to /index.php with do/subaction/story.
        session = _anon_http()
        try:
            r = search_request(session.get,
                _BASE + "/index.php",
                params={"do": "search", "subaction": "search", "story": query},
                headers={"Referer": _BASE + "/"},
                timeout=30,
            )
        except requests.RequestException:
            return None
        finally:
            _last_search = time.monotonic()
        if r.status_code != 200:
            raise SearchError(f"Online-Fix returned HTTP {r.status_code}. Press r to retry.")
        cooldown = _cooldown_seconds(r.text)
        if cooldown is None:
            if not _RESULT_BLOCK_RE.search(r.text) and _SEARCH_FORM not in r.text:
                raise SearchError("Online-Fix returned an unrecognized page (site layout or "
                                  "protection may have changed). Press r to retry.")
            return r.text
        wait = cooldown + 0.5
    raise SearchError("Online-Fix is still asking to wait between searches. Press r to retry in a few seconds.")


def _result_blocks(html: str):
    """Each result block of a search page, ending before the sidebar."""
    starts = [m.start() for m in _RESULT_BLOCK_RE.finditer(html)]
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(html)
        sidebar = _RESULTS_END_RE.search(html, start, end)
        yield html[start:sidebar.start() if sidebar else end]


def _parse_results(html: str, query: str) -> list[SearchResult]:
    """Rows from the search page's result blocks only, never from its sidebar."""
    results: list[SearchResult] = []
    seen: set[str] = set()
    for block in _result_blocks(html):
        m = _GAME_HREF_RE.search(block)
        if not m:
            continue
        path, post_id = m.group(1), m.group(2)
        if post_id in seen:
            continue
        seen.add(post_id)
        url = _BASE + path
        # Title: the block's <h2 class="title">, else the cover <img alt="…">
        # or a title="…" attribute, then the de-slugified URL.
        title_m = _H2_TITLE_RE.search(block) or _ALT_ATTR_RE.search(block) or _TITLE_ATTR_RE.search(block)
        name = _strip_tags(title_m.group(1)) if title_m else ""
        name = name or _deslug(path)
        if not matches_name(name, query):
            continue
        results.append(SearchResult(
            name=name,
            info_hash=post_id,    # placeholder; no public hash exists
            seeders=0,          # online-fix listing carries no swarm stats
            leechers=0,
            size=0,             # unknown until the .torrent is parsed
            source="Online-Fix",
            page_url=url,
            handle={"of_post_url": url},      # explicit handle for the download resolver
        ))
    return results


def _absolutize(href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return _BASE + href
    return href


def _torrent_url_in_dir(dir_url: str) -> str | None:
    """List an uploads-host directory (referer-gated nginx autoindex) and return
    the first ``.torrent`` URL inside, or None."""
    try:
        r = _anon_http().get(dir_url, headers=_REFERER, timeout=25)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    for href in re.findall(r'href="([^"]+)"', r.text):
        if href.lower().endswith(".torrent"):
            return urljoin(dir_url, unescape(href))
    return None


def resolve_torrent(post_url: str) -> str | None:
    """Resolve the downloadable ``.torrent`` URL for a post, or None. No login
    needed.

    The post page is public; online-fix links a per-game directory on its uploads
    host (e.g. ``https://uploads.online-fix.me:2053/torrents/<Game>/``) that holds
    the file. We take a direct ``.torrent`` link if one is present, else list that
    directory and pick the ``.torrent`` inside. The uploads host gates by HTTP
    referer (not auth), handled in ``_torrent_url_in_dir`` / ``download_torrent_file``.
    """
    if not post_url:
        return None
    try:
        r = _anon_http().get(post_url, timeout=25)
    except requests.RequestException:
        return None
    m = _TORRENT_HREF_RE.search(r.text)
    if m:
        return _absolutize(unescape(m.group(1)))
    m = _TORRENT_DIR_RE.search(r.text)
    if not m:
        return None
    return _torrent_url_in_dir(_absolutize(unescape(m.group(1))))


def download_torrent_file(torrent_url: str, dest_path) -> bool:
    """Stream a ``.torrent`` to ``dest_path``. Returns True on success. The uploads
    host is referer-gated (not login-gated), so every request carries the site
    referer; no session/login required."""
    if not torrent_url:
        return False
    try:
        with _anon_http().get(torrent_url, headers=_REFERER, timeout=30, stream=True) as resp:
            resp.raise_for_status()
            with open(dest_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        fh.write(chunk)
    except (requests.RequestException, OSError):
        return False
    return True


def fetch_torrent_for(post_url: str, dest_dir: str) -> str | None:
    """Resolve and download a post's ``.torrent`` into ``dest_dir``; return the
    saved file path, or None. This is the 'hand to the system client' entry point
    used by main.py — resolve the URL, then stream the file to disk.
    """
    turl = resolve_torrent(post_url)
    if not turl:
        return None
    fname = unquote(turl.rsplit("/", 1)[-1]) or "online-fix.torrent"
    if not fname.lower().endswith(".torrent"):
        fname += ".torrent"
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError:
        return None
    dest = os.path.join(dest_dir, fname)
    return dest if download_torrent_file(turl, dest) else None


def test_credentials(username: str, password: str) -> tuple[bool | None, str]:
    """Verify credentials by logging in. Returns (ok, message): True logged in,
    False rejected, None couldn't reach online-fix.me."""
    try:
        s = requests.Session()
        s.headers.update(_UA)
        _do_login(s, username, password)
    except requests.RequestException as e:
        return None, f"Couldn't reach online-fix.me ({type(e).__name__})"
    if _logged_in(s):
        return True, "Login successful"
    return False, "Login failed — check username/password"
