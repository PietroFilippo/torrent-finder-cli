"""Fetch rich torrent details from the origin site (Nyaa / PirateBay / YTS).

Each source exposes data differently, so there's a small adapter per engine:
  * Nyaa        — scrape the /view HTML page (no API).
  * Apibay (TPB)— JSON endpoints t.php (details) + f.php (file list).
  * YTS         — movie_details JSON API.
Other sources return ``(None, reason)`` so the caller can say "not available".

Also assesses whether subtitles are embedded in the video: a filename/metadata
heuristic always, plus a definitive ffprobe check when ffmpeg is installed and a
copy of the video has already been downloaded.
"""

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from html import unescape

import requests

from constants import get_download_dir

_UA = {"User-Agent": "Mozilla/5.0"}
_VIDEO_EXTS = (".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts")
_SUB_EXTS = (".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx")


@dataclass
class TorrentInfo:
    source: str
    title: str
    page_url: str = ""
    category: str = ""
    uploader: str = ""
    date: str = ""
    seeders: str = ""
    leechers: str = ""
    size: str = ""
    info_hash: str = ""
    description: str = ""
    files: list = field(default_factory=list)        # (name, size_str)
    embedded_subs: str = ""                            # human-readable assessment


# --------------------------------------------------------------------------- #
# HTML helpers
# --------------------------------------------------------------------------- #
def _strip_tags(html: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", html)).strip()


def _clean(html: str) -> str:
    """Strip tags but keep line breaks (<br>, block ends) for readable text."""
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|div|li)>", "\n", html)
    text = unescape(re.sub(r"<[^>]+>", "", html))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------- #
# Nyaa
# --------------------------------------------------------------------------- #
def _nyaa_field(html: str, label: str) -> str:
    # The value div sometimes carries extra attributes (e.g. Date has
    # data-timestamp), so allow anything up to the closing '>'.
    m = re.search(
        r'col-md-1">' + re.escape(label) + r':</div>\s*<div class="col-md-\d+"[^>]*>(.*?)</div>',
        html, re.S,
    )
    return _strip_tags(m.group(1)) if m else ""


def _fetch_nyaa(result: dict):
    url = result.get("page_url")
    if not url:
        return None, "No Nyaa page link for this result."
    try:
        html = requests.get(url, headers=_UA, timeout=20).text
    except Exception as e:
        return None, f"Couldn't reach Nyaa ({type(e).__name__})."

    title_m = re.search(r"<h3 class=\"panel-title\">(.*?)</h3>", html, re.S)
    info = TorrentInfo(
        source="Nyaa",
        title=_strip_tags(title_m.group(1)) if title_m else result.get("name", ""),
        page_url=url,
        category=_nyaa_field(html, "Category"),
        uploader=_nyaa_field(html, "Submitter"),
        date=_nyaa_field(html, "Date"),
        seeders=_nyaa_field(html, "Seeders"),
        leechers=_nyaa_field(html, "Leechers"),
        size=_nyaa_field(html, "File size"),
        info_hash=_nyaa_field(html, "Info hash") or result.get("info_hash", ""),
    )

    desc_m = re.search(r'id="torrent-description">(.*?)</div>', html, re.S)
    if desc_m:
        info.description = _clean(desc_m.group(1))

    flist_m = re.search(r'torrent-file-list panel-body">(.*?)</div>', html, re.S)
    if flist_m:
        for fm in re.finditer(
            r'fa-file"></i>\s*(.*?)\s*<span class="file-size">\((.*?)\)</span>',
            flist_m.group(1), re.S,
        ):
            info.files.append((_strip_tags(fm.group(1)), fm.group(2).strip()))

    return info, ""


# --------------------------------------------------------------------------- #
# Apibay (The Pirate Bay)
# --------------------------------------------------------------------------- #
def _fetch_apibay(result: dict):
    tid = ""
    m = re.search(r"id=(\d+)", result.get("page_url", ""))
    if m:
        tid = m.group(1)
    if not tid:
        return None, "No PirateBay id for this result."
    try:
        # apibay.org is slow (~20s behind Cloudflare) — use a generous timeout.
        d = requests.get("https://apibay.org/t.php", params={"id": tid}, timeout=25, headers=_UA).json()
        files = requests.get("https://apibay.org/f.php", params={"id": tid}, timeout=25, headers=_UA).json()
    except Exception as e:
        return None, f"Couldn't reach PirateBay API ({type(e).__name__})."

    info = TorrentInfo(
        source="Apibay",
        title=d.get("name", result.get("name", "")),
        page_url=result.get("page_url", ""),
        category=str(d.get("category", "")),
        uploader=d.get("username", ""),
        seeders=str(d.get("seeders", "")),
        leechers=str(d.get("leechers", "")),
        size=str(d.get("size", "")),
        info_hash=d.get("info_hash", result.get("info_hash", "")),
        description=_clean(d.get("descr", "")),
    )
    if isinstance(d.get("added"), str) and d["added"].isdigit():
        import datetime
        info.date = datetime.datetime.fromtimestamp(int(d["added"])).strftime("%Y-%m-%d")
    if isinstance(files, list):
        for f in files:
            name = f.get("name")
            if isinstance(name, list):
                name = name[0] if name else ""
            size = f.get("size")
            if isinstance(size, list):
                size = size[0] if size else 0
            if name:
                info.files.append((str(name), _human_size(size)))
    # Apibay exposes no comments endpoint.
    return info, ""


# --------------------------------------------------------------------------- #
# YTS
# --------------------------------------------------------------------------- #
def _fetch_yts(result: dict):
    url = result.get("page_url", "")
    try:
        r = requests.get(
            "https://yts.mx/api/v2/list_movies.json",
            params={"query_term": result.get("name", "")[:60], "limit": 1, "with_rt_ratings": "true"},
            timeout=15,
        ).json()
        movies = r.get("data", {}).get("movies", []) or []
    except Exception as e:
        return None, f"Couldn't reach YTS ({type(e).__name__})."
    if not movies:
        return None, "YTS returned no details for this title."
    mv = movies[0]
    info = TorrentInfo(
        source="YTS",
        title=mv.get("title_long", result.get("name", "")),
        page_url=url or mv.get("url", ""),
        category=", ".join(mv.get("genres", []) or []),
        date=str(mv.get("year", "")),
        description=_clean(mv.get("summary") or mv.get("description_full") or ""),
    )
    rating = mv.get("rating")
    if rating:
        info.description = f"IMDb rating: {rating}/10\n\n" + info.description
    return info, ""


# --------------------------------------------------------------------------- #
# Embedded-subtitle assessment
# --------------------------------------------------------------------------- #
def _human_size(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.1f} {unit}"
        n /= 1024


def _locate_local_video(name: str):
    """Find an already-downloaded video for this torrent, for ffprobe."""
    def toks(s):
        return set(re.findall(r"[a-z0-9]+", s.lower()))
    want = toks(name)
    best, best_score = None, 0
    try:
        for root, _dirs, files in os.walk(get_download_dir()):
            for fn in files:
                if fn.lower().endswith(_VIDEO_EXTS):
                    score = len(want & toks(fn))
                    if score > best_score:
                        best, best_score = os.path.join(root, fn), score
    except Exception:
        return None
    return best if best_score >= 2 else None


def _ffprobe_subtitle_tracks(path: str):
    """Return a list of subtitle-track descriptions, or None if ffprobe failed."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", path],
            capture_output=True, text=True, timeout=60,
        )
        streams = json.loads(out.stdout or "{}").get("streams", [])
    except (FileNotFoundError, json.JSONDecodeError, subprocess.SubprocessError, OSError):
        return None
    tracks = []
    for s in streams:
        if s.get("codec_type") == "subtitle":
            lang = (s.get("tags", {}) or {}).get("language", "und")
            tracks.append(f"{lang}/{s.get('codec_name', '?')}")
    return tracks


def assess_embedded_subs(result: dict, files: list) -> str:
    """Human-readable verdict on whether subtitles ship with the video.

    ``files`` is a list of (name, size) tuples (from the origin or DHT).
    """
    names = [f[0] for f in files] if files else [result.get("name", "")]
    has_separate = any(n.lower().endswith(_SUB_EXTS) for n in names)
    has_mkv = any(n.lower().endswith(".mkv") for n in names) or result.get("name", "").lower().endswith(".mkv")

    # Definitive check first: ffprobe a downloaded copy if ffmpeg is around.
    local = _locate_local_video(result.get("name", ""))
    if local:
        tracks = _ffprobe_subtitle_tracks(local)
        if tracks is not None:
            if tracks:
                return f"yes — {len(tracks)} embedded track(s): {', '.join(tracks[:6])} (ffprobe)"
            elif has_separate:
                return "no embedded tracks, but separate subtitle file(s) present (ffprobe)"
            else:
                return "no — no embedded tracks and no separate subs (ffprobe)"

    # Heuristic fallback.
    if has_separate:
        return "separate subtitle file(s) present in the torrent"
    tags = result.get("name", "").lower()
    cat = (result.get("category", "") or "").lower()
    sub_signal = any(t in tags for t in (
        "subbed", "softsub", "eng sub", "engsub", "multi-sub", "multisub",
        "dual audio", "dual-audio", "english", "vostfr", "10bit",
    )) or "english-translated" in cat
    if has_mkv and sub_signal:
        return "likely embedded — MKV with subtitle/translation tags (heuristic)"
    if has_mkv:
        return "uncertain — MKV without separate subs; may be soft-subbed or raw (heuristic)"
    return "no subtitle indications found (heuristic)"


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def fetch_torrent_info(result: dict):
    """Fetch origin details for a result. Returns ``(TorrentInfo | None, reason)``."""
    source = result.get("source", "")
    if source == "Nyaa":
        info, err = _fetch_nyaa(result)
    elif source == "Apibay":
        info, err = _fetch_apibay(result)
    elif source == "YTS":
        info, err = _fetch_yts(result)
    else:
        return None, f"Origin info isn't available for {source or 'this source'}."
    if info is not None:
        info.embedded_subs = assess_embedded_subs(result, info.files)
    return info, err
