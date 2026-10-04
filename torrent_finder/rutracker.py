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
configured, searches report that a login is required. This is
HTML scraping behind a login, so it's inherently fragile: a RuTracker layout
change will need updates here.
"""

import re
import threading
import time
from html import unescape

import requests

from torrent_finder.search_errors import SearchError, login_required
from torrent_finder.search_result import SearchResult
from torrent_finder.search_control import search_request

from torrent_finder.credentials import rutracker_config

_BASE = "https://rutracker.org/forum"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

_session: requests.Session | None = None
_session_credentials: tuple[str, str] | None = None
_session_lock = threading.Lock()
# Login outcomes that repeating can't fix: Cloudflare's check is not retried for
# a few minutes, rejected credentials / a captcha not until they change.
_BLOCK_BACKOFF = 300.0
_blocked_until = 0.0  # Cloudflare's check or a captcha: no login attempt before this
_blocked_reason = "blocked"
_failed_login: str = ""  # "rejected" for _session_credentials, until they change

_LOGIN_ERRORS = {
    "blocked": ("RuTracker's Cloudflare browser check blocked the app (this is not a password problem; "
                "your credentials weren't checked). The app can't pass that check, so it won't try again "
                "for a few minutes.", "blocked"),
    "captcha": ("RuTracker asks for a captcha after failed logins. Log in once at rutracker.org in your "
                "browser; the app tries again in a few minutes.", "login_error"),
    "rejected": ("RuTracker rejected the login. Check your saved credentials in Credentials.", "rejected_login"),
    "unreachable": ("RuTracker could not be reached. Try again later.", "error"),
    "unexpected": ("RuTracker returned an unexpected login page. Try again later.", "error"),
}


def _login_error(reason: str) -> SearchError:
    """A new error for *reason*: a shared instance would collect every raise's traceback."""
    message, status = _LOGIN_ERRORS[reason]
    return SearchError(message, status=status)

_ROW_RE = re.compile(r'<tr id="trs-tr-\d+".*?</tr>', re.S)


def _strip_tags(html: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", html)).strip()


def _is_challenge(response: requests.Response) -> bool:
    """Cloudflare's "Just a moment…" browser check, which a script can't pass.

    Ordinary Cloudflare pages also load its challenge-platform script, so the
    marker alone isn't enough: the check comes with an error status.
    """
    return response.headers.get("cf-mitigated") == "challenge" or (
        response.status_code in (403, 429, 503)
        and ("Just a moment" in response.text or "cf-chl" in response.text))


def _login(username: str, password: str) -> tuple[requests.Session | None, str]:
    """Log in; ``(session, "ok")`` or ``(None, reason)`` with reason "blocked"
    (Cloudflare's check), "captcha", "rejected", "unreachable" or "unexpected".
    RuTracker forms are Windows-1251, so the body is cp1251-encoded and percent-escaped;
    characters cp1251 lacks ("coração") become character references, as browsers send them."""
    s = requests.Session()
    s.headers.update(_UA)
    fields = {"login_username": username, "login_password": password, "login": "вход"}
    body = "&".join(
        f"{k}={requests.utils.quote(str(v).encode('cp1251', errors='xmlcharrefreplace'))}"
        for k, v in fields.items()
    )
    try:
        r = search_request(s.post,
            f"{_BASE}/login.php",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=25,
        )
    except requests.RequestException:
        return None, "unreachable"
    if "bb_session" in s.cookies.get_dict():
        return s, "ok"
    if _is_challenge(r):
        return None, "blocked"
    r.encoding = "cp1251"
    if "cap_sid" in r.text or "captcha" in r.text.casefold():
        return None, "captcha"
    if r.status_code == 200 and "login_username" in r.text:
        return None, "rejected"  # the login form came back
    return None, "unexpected"


def _get_session() -> requests.Session:
    """A logged-in session (cached for the process). Raises ``SearchError``
    explaining why not, without repeating a login that can't succeed yet."""
    global _session, _session_credentials, _blocked_until, _blocked_reason, _failed_login
    with _session_lock:
        cfg = rutracker_config()
        auth = (cfg["username"], cfg["password"]) if cfg else None
        if auth != _session_credentials:
            if _session is not None:
                _session.close()
            _session, _session_credentials, _blocked_until, _failed_login = None, auth, 0.0, ""
        if time.monotonic() < _blocked_until:  # also with a session: the backoff covers every request
            raise _login_error(_blocked_reason)
        if _session is not None:
            return _session
        if not auth:
            raise login_required("RuTracker")
        if _failed_login:
            raise _login_error(_failed_login)
        session, reason = _login(*auth)
        if session is None:
            if reason in ("blocked", "captcha"):
                _blocked_until, _blocked_reason = time.monotonic() + _BLOCK_BACKOFF, reason
            elif reason == "rejected":
                _failed_login = reason
            raise _login_error(reason)
        _session = session
        return _session


def search(query: str) -> list[SearchResult]:
    """Search RuTracker. Returns SearchResult rows with the topic id as a placeholder
    ``info_hash`` (resolve the real one with ``resolve_info_hash`` on select).
    Login and access problems raise ``SearchError`` with a specific status."""
    global _session, _blocked_until, _blocked_reason
    session = _get_session()
    try:
        r = search_request(session.get, f"{_BASE}/tracker.php", params={"nm": query}, timeout=30)
    except requests.RequestException:
        return []
    if _is_challenge(r):
        with _session_lock:
            _blocked_until, _blocked_reason = time.monotonic() + _BLOCK_BACKOFF, "blocked"
        raise _login_error("blocked")
    if r.status_code in (401, 403) or "login.php" in r.url:
        with _session_lock:
            _session = None  # log in again on the next search
        raise SearchError("RuTracker ended the login session. Press r to log in again.", status="login_error")
    r.encoding = "cp1251"
    html = r.text

    results: list[SearchResult] = []
    for row in _ROW_RE.findall(html):
        tid = re.search(r'data-topic_id="(\d+)"', row)
        title = re.search(r'class="[^"]*tt-text[^"]*"[^>]*>(.*?)</a>', row, re.S)
        size = re.search(r'tor-size"\s+data-ts_text="(\d+)"', row)
        if not (tid and title and size):
            continue
        seeders = re.search(r'class="seedmed"[^>]*>(\d+)', row)
        leechers = re.search(r'leechmed[^>]*>(\d+)<', row)
        results.append(SearchResult(
            name=_strip_tags(title.group(1)),
            info_hash=tid.group(1),  # placeholder; real hash resolved on select
            seeders=seeders.group(1) if seeders else 0,
            leechers=leechers.group(1) if leechers else 0,
            size=size.group(1),      # bytes
            source="RuTracker",
            page_url=f"{_BASE}/viewtopic.php?t={tid.group(1)}",
            handle={"rt_topic_id": tid.group(1)},
        ))
    return results


def resolve_info_hash(topic_id: str) -> str | None:
    """Fetch a topic page and pull out its real info hash (search rows don't
    carry magnets). Returns a 40-char lowercase hex hash, or None."""
    global _session
    if not topic_id:
        return None
    for _attempt in range(2):
        try:
            session = _get_session()
        except SearchError:
            return None
        try:
            r = session.get(f"{_BASE}/viewtopic.php", params={"t": topic_id}, timeout=25)
            r.encoding = "cp1251"
        except requests.RequestException:
            return None
        if "login.php" not in r.url:
            break
        with _session_lock:
            if _session is session:
                _session = None  # the login expired: log in again once
    else:
        return None
    m = re.search(r"magnet:\?xt=urn:btih:([A-Fa-f0-9]{40})", r.text)
    return m.group(1).lower() if m else None


def test_credentials(username: str, password: str) -> tuple[bool | None, str]:
    """Verify credentials by logging in. Returns (ok, message): True logged in,
    False rejected, None couldn't reach RuTracker."""
    session, reason = _login(username, password)
    return {
        "ok": (True, "Login successful"),
        "rejected": (False, "Login failed — check username/password"),
        "captcha": (False, "RuTracker wants a captcha after failed logins — log in once in your browser"),
        "blocked": (None, "RuTracker's Cloudflare browser check blocked the app — credentials not tested"),
        "unreachable": (None, "Couldn't reach RuTracker"),
        "unexpected": (None, "RuTracker returned an unexpected page"),
    }[reason]
