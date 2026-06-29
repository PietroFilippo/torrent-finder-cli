"""RuTracker search client — login + HTML scrape (no official API).

RuTracker needs a login to search and exposes magnets only on topic pages, not
in the search results. So this module:

  1. logs in once (a cp1251-encoded form POST) and caches the session,
  2. scrapes ``tracker.php?nm=<query>`` for the display rows (title / size /
     seeders / leechers), using the numeric topic id as a placeholder
     ``info_hash`` so a search costs a single request,
  3. resolves the real magnet lazily from the topic page when a result is
     actually picked (``resolve_info_hash``) — one request, not one per row.

Credentials come from ``credentials.py`` (env var or gitignored file). With none
configured, every call returns nothing so the provider stays dormant. This is
HTML scraping behind a login, so it's inherently fragile: a RuTracker layout
change will need updates here.
"""

import re
import threading
from html import unescape

import requests

from torrent_finder.credentials import rutracker_config

_BASE = "https://rutracker.org/forum"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

_session: requests.Session | None = None
_session_lock = threading.Lock()

_ROW_RE = re.compile(r'<tr id="trs-tr-\d+".*?</tr>', re.S)


def _strip_tags(html: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", html)).strip()


def _post_login(username: str, password: str) -> requests.Session | None:
    """Log in and return the session, or None on failure. RuTracker forms are
    Windows-1251, so the body is cp1251-encoded and percent-escaped."""
    s = requests.Session()
    s.headers.update(_UA)
    fields = {"login_username": username, "login_password": password, "login": "вход"}
    body = "&".join(
        f"{k}={requests.utils.quote(str(v).encode('cp1251'))}" for k, v in fields.items()
    )
    try:
        s.post(
            f"{_BASE}/login.php",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=25,
        )
    except requests.RequestException:
        return None
    return s if "bb_session" in s.cookies.get_dict() else None


def _get_session() -> requests.Session | None:
    """Return a logged-in session (cached for the process), or None."""
    global _session
    with _session_lock:
        if _session is None:
            cfg = rutracker_config()
            if cfg:
                _session = _post_login(cfg["username"], cfg["password"])
        return _session


def search(query: str) -> list[dict]:
    """Search RuTracker. Returns result dicts with the topic id as a placeholder
    ``info_hash`` (resolve the real one with ``resolve_info_hash`` on select)."""
    session = _get_session()
    if session is None:
        return []
    try:
        r = session.get(f"{_BASE}/tracker.php", params={"nm": query}, timeout=30)
        r.encoding = "cp1251"
        html = r.text
    except requests.RequestException:
        return []

    results: list[dict] = []
    for row in _ROW_RE.findall(html):
        tid = re.search(r'data-topic_id="(\d+)"', row)
        title = re.search(r'class="[^"]*tt-text[^"]*"[^>]*>(.*?)</a>', row, re.S)
        size = re.search(r'tor-size"\s+data-ts_text="(\d+)"', row)
        if not (tid and title and size):
            continue
        seeders = re.search(r'class="seedmed"[^>]*>(\d+)', row)
        leechers = re.search(r'leechmed[^>]*>(\d+)<', row)
        results.append({
            "name": _strip_tags(title.group(1)),
            "info_hash": tid.group(1),  # placeholder; real hash resolved on select
            "seeders": seeders.group(1) if seeders else "0",
            "leechers": leechers.group(1) if leechers else "0",
            "size": size.group(1),      # bytes
            "source": "RuTracker",
            "page_url": f"{_BASE}/viewtopic.php?t={tid.group(1)}",
            "rt_topic_id": tid.group(1),
        })
    return results


def resolve_info_hash(topic_id: str) -> str | None:
    """Fetch a topic page and pull out its real info hash (search rows don't
    carry magnets). Returns a 40-char lowercase hex hash, or None."""
    session = _get_session()
    if session is None or not topic_id:
        return None
    try:
        r = session.get(f"{_BASE}/viewtopic.php", params={"t": topic_id}, timeout=25)
        r.encoding = "cp1251"
    except requests.RequestException:
        return None
    m = re.search(r"magnet:\?xt=urn:btih:([A-Fa-f0-9]{40})", r.text)
    return m.group(1).lower() if m else None


def test_credentials(username: str, password: str) -> tuple[bool | None, str]:
    """Verify credentials by logging in. Returns (ok, message): True logged in,
    False rejected, None couldn't reach RuTracker."""
    try:
        s = requests.Session()
        s.headers.update(_UA)
        fields = {"login_username": username, "login_password": password, "login": "вход"}
        body = "&".join(
            f"{k}={requests.utils.quote(str(v).encode('cp1251'))}" for k, v in fields.items()
        )
        s.post(
            f"{_BASE}/login.php",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=25,
        )
    except requests.RequestException as e:
        return None, f"Couldn't reach RuTracker ({type(e).__name__})"
    if "bb_session" in s.cookies.get_dict():
        return True, "Login successful"
    return False, "Login failed — check username/password"
