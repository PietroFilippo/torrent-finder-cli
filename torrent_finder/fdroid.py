"""F-Droid search and APK download — the official repository, no account.

F-Droid publishes free and open-source Android apps. It fills gaps the torrent
indexes leave for such apps: in the 2026-10-03 audit, Organic Maps, K-9 Mail
and AnkiDroid had no torrent candidate but are on F-Droid. It has no
commercial games or apps.

  1. ``search`` asks F-Droid's public search API. A row names the app and its
     package, the exact identity ("VLC [org.videolan.vlc]"), so look-alikes
     such as remotes and plugins stay distinguishable.
  2. A pick asks the package API for the repository's suggested version and
     downloads that APK from ``https://f-droid.org/repo/`` over HTTPS, the
     same file F-Droid's website links. Downloads from anywhere else are
     refused.

Android checks the APK's signature when it is installed. F-Droid also
publishes a PGP signature beside each APK (``….apk.asc``); the app links it
but does not check it.
"""

import os
import re
from urllib.parse import urlsplit

import requests

from torrent_finder.direct_download import Cancelled, save_response
from torrent_finder.search_control import search_request
from torrent_finder.search_result import SearchResult

_SEARCH_URL = "https://search.f-droid.org/api/search_apps"
_PACKAGE_API = "https://f-droid.org/api/v1/packages/"
REPO_URL = "https://f-droid.org/repo/"
_UA = {"User-Agent": "torrent-finder-cli"}
_MAX_ROWS = 30

# Android package names: dot-separated Java identifiers.
_PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+")
_PACKAGE_URL = re.compile(r"/packages/([^/?#]+)/?$")
# App names often carry a tagline: "Organic Maps・Offline Map & GPS".
_TAGLINE = re.compile(r"\s*(?:・|·|\||–|—| - |: ).*$")


def search(query: str) -> list[SearchResult]:
    """F-Droid apps matching *query*; a failed request raises (a retryable failure)."""
    response = search_request(requests.get, _SEARCH_URL, params={"q": query, "lang": "en"},
                              headers=_UA, timeout=15)
    response.raise_for_status()
    apps = response.json().get("apps")
    if not isinstance(apps, list):
        from torrent_finder.search_diagnostics import record_failure
        record_failure(message="F-Droid's response did not contain an app list.")
        return []
    rows = []
    for app in apps[:_MAX_ROWS]:
        if not isinstance(app, dict):
            continue
        match = _PACKAGE_URL.search(str(app.get("url") or ""))
        package = match.group(1) if match else ""
        if not _PACKAGE.fullmatch(package):
            continue
        name = " ".join(str(app.get("name") or package).split())
        rows.append(SearchResult(
            name=f"{name} [{package}]",
            info_hash=f"fdroid:{package}",  # placeholder; no torrent exists
            source="F-Droid",
            page_url=f"https://f-droid.org/en/packages/{package}/",
            handle={"fd_package": package},
            extra={"fd_app": _TAGLINE.sub("", name) or name, "fd_summary": str(app.get("summary") or "")},
        ))
    return rows


def suggested_apk(package: str) -> "tuple[str, str] | None":
    """(APK URL, version name) of the repository's suggested version, or None."""
    if not _PACKAGE.fullmatch(package or ""):
        return None
    try:
        response = requests.get(_PACKAGE_API + package, headers=_UA, timeout=20)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return None
    code = data.get("suggestedVersionCode") if isinstance(data, dict) else None
    if not isinstance(code, int) or isinstance(code, bool) or code <= 0:
        return None
    version = next((str(p.get("versionName") or "") for p in data.get("packages") or []
                    if isinstance(p, dict) and p.get("versionCode") == code), "")
    return f"{REPO_URL}{package}_{code}.apk", version


def download_apk(url: str, dest_dir: str, cancel_event=None, progress_cb=None) -> "str | None":
    """Save an APK from F-Droid's repository into *dest_dir*; the saved path or None.

    Only ``https://f-droid.org/repo/`` URLs are fetched, and a response that
    ended up anywhere else is discarded."""
    if not url.startswith(REPO_URL):
        return None
    filename = url.rsplit("/", 1)[-1]
    try:
        os.makedirs(dest_dir, exist_ok=True)
        with requests.get(url, headers=_UA, timeout=60, stream=True) as response:
            final = urlsplit(response.url)
            if response.status_code != 200 or (final.scheme, final.netloc) != ("https", "f-droid.org"):
                return None
            return save_response(response, dest_dir, filename, cancel_event, progress_cb)
    except (Cancelled, requests.RequestException, OSError):
        return None
