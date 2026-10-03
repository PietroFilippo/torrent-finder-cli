"""Bounded catalog supplement for older titles crowded out of Nyaa's RSS feed."""

import re
from collections import Counter
from html.parser import HTMLParser

import requests

from torrent_finder.search_result import SearchResult
from torrent_finder.search_control import search_request
from torrent_finder.result_view import media_title, title_score, words


def discovery_query(query: str, recent: list[SearchResult]) -> str:
    """Exclude dominant unrelated title prefixes for one supplemental request.

    The original results are retained. This bounded discovery pass can uncover
    an older exact title without walking dozens of recent-upload pages.
    """
    wanted = words(query)
    prefixes = Counter(
        tokens[0] for row in recent
        if title_score(row.name, query) < 2
        if (tokens := words(media_title(row.name)))
        if len(tokens[0]) >= 3 and tokens[0] not in wanted
    )
    excluded = [word for word, count in prefixes.most_common(4) if count >= 3]
    return " ".join([query, *(f"-{word}" for word in excluded)])


class _Catalog(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.cells = None
        self.in_cell = False
        self.name = self.info_hash = self.url = ""
        self.uploaded_at = 0
        self.has_more = False
        self.is_catalog = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table" and "torrent-list" in attrs.get("class", ""):
            self.is_catalog = True
        if tag == "a" and "p=" in attrs.get("href", "") and attrs.get("rel") == "next":
            self.has_more = True
        if tag == "tr":
            self.cells = []
            self.name = self.info_hash = self.url = ""
            self.uploaded_at = 0
        elif self.cells is not None and tag == "td":
            self.cells.append("")
            self.in_cell = True
            self.uploaded_at = attrs.get("data-timestamp", self.uploaded_at)
        elif self.cells is not None and tag == "a":
            href = attrs.get("href", "")
            if re.fullmatch(r"/view/\d+", href):
                self.name = attrs.get("title", "")
                self.url = "https://nyaa.si" + href
            match = re.search(r"xt=urn:btih:([a-fA-F0-9]{40})", href)
            if match:
                self.info_hash = match.group(1).lower()

    def handle_data(self, data):
        if self.cells and self.in_cell:
            self.cells[-1] += data

    def handle_endtag(self, tag):
        if tag == "td":
            self.in_cell = False
        elif tag == "tr" and self.cells is not None:
            if len(self.cells) >= 8 and self.name and self.info_hash:
                size = re.search(r"([\d.]+)\s*([KMGT])i?B", self.cells[3], re.I)
                size_bytes = int(float(size[1]) * 1024 ** ("KMGT".index(size[2].upper()) + 1)) if size else 0
                self.rows.append(SearchResult(
                    name=self.name, info_hash=self.info_hash, page_url=self.url,
                    source="Nyaa", seeders=self.cells[5].strip(),
                    leechers=self.cells[6].strip(), size=size_bytes,
                    uploaded_at=self.uploaded_at,
                ))
            self.cells = None


def popular(query: str, category: str) -> list[SearchResult]:
    try:
        response = search_request(requests.get, "https://nyaa.si/", params={
            "q": query, "c": category, "s": "seeders", "o": "desc",
        }, timeout=10)
        response.raise_for_status()
        parser = _Catalog()
        parser.feed(response.text)
        return parser.rows
    except (requests.RequestException, ValueError) as error:
        from torrent_finder.search_diagnostics import record_failure
        record_failure(error)
        return []


def search_page(query: str, category: str, page: int):
    """Fetch one chronological catalog page; RSS is a separate first request."""
    from torrent_finder.search_session import PageRows
    from torrent_finder.search_errors import SearchError
    response = search_request(requests.get, "https://nyaa.si/", params={
        "q": query, "c": category, "p": page, "s": "id", "o": "desc",
    }, timeout=10)
    response.raise_for_status()
    parser = _Catalog()
    parser.feed(response.text)
    if not parser.is_catalog and "No results found" not in response.text:
        raise SearchError("Nyaa returned an unrecognized catalog page.")
    # The site uses a next-page anchor, including when rel=next is absent.
    from urllib.parse import parse_qs, urlparse
    links = re.findall(r'href=[\"\']([^\"\']+)[\"\']', response.text)
    from html import unescape
    more = any(parse_qs(urlparse(unescape(link)).query).get("p") == [str(page + 1)] for link in links)
    return PageRows(parser.rows, has_more=more)
