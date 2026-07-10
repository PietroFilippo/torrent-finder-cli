"""FitGirl Repacks search client — anonymous HTML scrape (no login, no API).

fitgirl-repacks.site is the official home of FitGirl's game repacks — heavily
compressed installers distributed via **public magnet links**. Fake "FitGirl"
uploads on public trackers are a known malware vector, so the official site is
the one trustworthy source; that's the point of this dedicated client.

Everything is public (no login, no Cloudflare challenge at the time of writing),
so this module is the simplest of the dedicated site clients:

  1. search the WordPress listing (``/?s=<query>``) for repack posts — title,
     post URL and repack size come straight from the search excerpt; the numeric
     post id is a placeholder ``info_hash`` so a search costs one request (two
     when a second results page exists),
  2. resolve the real magnet lazily from the post page when a result is picked
     (``resolve_info_hash``) — the first magnet on the page is the current
     release (older-version torrents further down are ignored).

Like the other site clients this is HTML scraping and inherently fragile: a
site theme change will need updates here. The markup keyed on is WordPress
boilerplate (``<article id="post-N" class="… category-lossless-repack …">``,
``<h1 class="entry-title">``), which has been stable for years.
"""

import re
import threading
from html import unescape

import requests

from torrent_finder.search_result import SearchResult

_BASE = "https://fitgirl-repacks.site"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

_session: requests.Session | None = None
_session_lock = threading.Lock()

_ARTICLE_RE = re.compile(r"<article\b.*?</article>", re.S)
_POST_ID_RE = re.compile(r'id="post-(\d+)"')
_TITLE_RE = re.compile(r'<h1 class="entry-title"><a href="([^"]+)"[^>]*>(.*?)</a>', re.S)
# Excerpts carry "Repack Size: from 55.7 GB [Selective Download]" — the number
# after an optional "from" is the (approximate) download size.
_SIZE_RE = re.compile(r"Repack Size:\s*(?:from\s*)?([\d.,]+)\s*([KMGT]B)", re.I)
# "Older" pagination link at the bottom of a results page → a second page exists.
_NEXT_PAGE_RE = re.compile(r'class="next page-numbers"')
_MAGNET_RE = re.compile(r"magnet:\?xt=urn:btih:([A-Fa-f0-9]{40})")
_TAG_RE = re.compile(r"<[^>]+>")

_UNIT_BYTES = {"KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}


def _strip_tags(html: str) -> str:
    return unescape(_TAG_RE.sub("", html)).strip()


def _http() -> requests.Session:
    """Cached anonymous session (the site needs no cookies, but reusing one
    connection keeps the two-page search fast)."""
    global _session
    with _session_lock:
        if _session is None:
            s = requests.Session()
            s.headers.update(_UA)
            _session = s
        return _session


def _parse_size(article: str) -> str:
    """Approximate repack size in bytes (as a string), '0' when the excerpt
    doesn't carry one. Sizes are 'from X GB' for selective downloads, so this is
    a floor, not an exact figure."""
    m = _SIZE_RE.search(article)
    if not m:
        return "0"
    try:
        num = float(m.group(1).replace(",", ""))
    except ValueError:
        return "0"
    return str(int(num * _UNIT_BYTES.get(m.group(2).upper(), 1)))


def _parse_page(html: str, results: list[SearchResult], seen: set[str]) -> None:
    """Append one search page's repack posts to ``results`` (dedup on post id).

    Only ``category-lossless-repack`` articles are repacks — the search also
    returns site news / digest posts (``category-uncategorized`` etc.), which
    have no torrent and are skipped.
    """
    for article in _ARTICLE_RE.findall(html):
        if "category-lossless-repack" not in article:
            continue
        pid_m = _POST_ID_RE.search(article)
        title_m = _TITLE_RE.search(article)
        if not (pid_m and title_m):
            continue
        post_id = pid_m.group(1)
        if post_id in seen:
            continue
        seen.add(post_id)
        url = title_m.group(1)
        results.append(SearchResult(
            name=_strip_tags(title_m.group(2)) or "Unknown",
            # "fitgirl-" prefix keeps the placeholder from colliding with other
            # engines' numeric placeholders (Online-Fix post ids) in the merged
            # Games results, where dedupe is by info_hash.
            info_hash=f"fitgirl-{post_id}",
            seeders=0,          # the listing carries no swarm stats
            leechers=0,
            size=_parse_size(article),
            source="FitGirl",
            page_url=url,
            handle={"fg_post_url": url},      # explicit handle for the magnet resolver
        ))


def search(query: str) -> list[SearchResult]:
    """Search fitgirl-repacks.site. Returns SearchResult rows with a placeholder
    ``info_hash`` (resolve the real one with ``resolve_info_hash`` on select).
    No login needed. Empty list on any error.

    WordPress paginates search at 10 posts, so when page 1 is full and links a
    next page, page 2 is fetched too (capped there — 20 results is plenty).
    """
    session = _http()
    results: list[SearchResult] = []
    seen: set[str] = set()
    try:
        r = session.get(f"{_BASE}/", params={"s": query}, timeout=30)
        _parse_page(r.text, results, seen)
        if _NEXT_PAGE_RE.search(r.text):
            r2 = session.get(f"{_BASE}/page/2/", params={"s": query}, timeout=30)
            _parse_page(r2.text, results, seen)
    except requests.RequestException:
        return results  # keep whatever page 1 yielded
    return results


def resolve_info_hash(post_url: str) -> str | None:
    """Fetch a repack post and pull out its info hash (search excerpts carry no
    magnet). The first magnet on the page is the current release — Cyberpunk-style
    posts keep older-version torrents further down, which are ignored. Returns a
    40-char lowercase hex hash, or None."""
    if not post_url:
        return None
    try:
        r = _http().get(post_url, timeout=25)
    except requests.RequestException:
        return None
    m = _MAGNET_RE.search(r.text)
    return m.group(1).lower() if m else None
