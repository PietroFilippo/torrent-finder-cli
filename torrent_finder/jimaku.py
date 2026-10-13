"""Anime subtitle lookups via Jimaku (https://jimaku.cc).

Jimaku indexes Japanese/English fansub files (.srt/.ass) keyed by series,
which the western-TV providers behind subliminal don't cover well. Requires a
free API key (Jimaku account → settings), read from ``JIMAKU_API_KEY`` — see
``credentials.py``. With no key configured every call returns ``None`` so the
caller transparently falls back to subliminal.
"""

# i18n: converted
import os
import re
from typing import Optional

import requests
from rich.markup import escape

from torrent_finder.constants import console, get_download_dir
from torrent_finder.i18n import N_, t
from torrent_finder.ui import theme
from torrent_finder.credentials import jimaku_api_key

_BASE = "https://jimaku.cc/api"
_SUB_EXTS = (".srt", ".ass", ".ssa", ".vtt", ".sub")


def _headers(key: str) -> dict:
    return {"Authorization": key}


def _clean_title(torrent_name: str) -> str:
    """Reduce a fansub release name to a searchable series title.

    e.g. ``[Group] Spy x Family - 12 [1080p][HEVC].mkv`` -> ``Spy x Family``.
    """
    name = torrent_name
    name = re.sub(r"\[[^\]]*\]", " ", name)      # [Group], [1080p], ...
    name = re.sub(r"\([^)]*\)", " ", name)        # (2024), (BD), ...
    name = re.sub(r"\.(mkv|mp4|avi)$", " ", name, flags=re.IGNORECASE)
    # Drop a trailing " - 12" / " - 01v2" episode marker and anything after it.
    name = re.split(r"\s-\s*\d+", name)[0]
    name = re.sub(r"\b(1080p|720p|480p|2160p|x26[45]|hevc|bd|web|remux)\b", " ", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", name).strip(" -_.")
    return name


def _search_entries(query: str, key: str) -> list[dict]:
    try:
        resp = requests.get(
            f"{_BASE}/entries/search",
            params={"query": query},
            headers=_headers(key),
            timeout=15,
        )
        if resp.status_code == 401:
            console.print(t("[warning]Jimaku rejected the API key (401).[/warning]"))
            return []
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _list_files(entry_id: int, key: str) -> list[dict]:
    try:
        resp = requests.get(
            f"{_BASE}/entries/{entry_id}/files",
            headers=_headers(key),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _download(url: str, name: str, key: str) -> Optional[str]:
    """Save one subtitle file; an existing file of that name is kept (the new one
    is numbered) and a failed transfer leaves nothing behind."""
    from torrent_finder.direct_download import save_response
    dl_dir = get_download_dir()
    try:
        os.makedirs(dl_dir, exist_ok=True)
        with requests.get(url, headers=_headers(key), timeout=30, stream=True) as resp:
            resp.raise_for_status()
            return save_response(resp, dl_dir, name or "subtitle.srt")
    except Exception as e:
        console.print(t("[error]Jimaku download failed: {value}[/error]", value=escape(str(e))))
        return None


def _entry_label(entry: dict) -> str:
    return (
        entry.get("english_name")
        or entry.get("name")
        or entry.get("japanese_name")
        or t("entry {value}", value=entry.get('id', '?'))
    )


def search_and_download(torrent_name: str) -> Optional[str]:
    """Find anime subtitles on Jimaku and save the chosen file.

    Returns the saved path, or ``None`` (no key, no match, cancelled, or
    error) so the caller can fall back to subliminal.
    """
    key = jimaku_api_key()
    if not key:
        return None

    from torrent_finder.ui.selector import SelectItem, arrow_select  # local: avoid UI coupling at import

    console.print(
        t("[dim]Note: Jimaku lists community anime fansubs by series (mostly Japanese/English) — you pick the file/episode manually, and the comma-separated language option doesn't apply here.[/dim]")
    )
    query = _clean_title(torrent_name)
    console.print(t("[info]Searching Jimaku for:[/info] [highlight]{query}[/highlight]", query=escape(query)))

    with console.status(t("[accent]Querying Jimaku...[/accent]"), spinner=theme.SPINNER):
        entries = _search_entries(query, key)
    if not entries:
        console.print(t("[warning]No Jimaku series matched — trying subliminal instead.[/warning]"))
        return None

    # Pick the series (auto when there's only one match).
    if len(entries) == 1:
        entry = entries[0]
    else:
        items = [SelectItem(label=_entry_label(e), value=e, is_action=True) for e in entries[:25]]
        items.append(SelectItem(label=t("Cancel"), value=None, is_action=True))
        idx = arrow_select(items, title=t("Jimaku series"))
        if idx is None or items[idx].value is None:
            return None
        entry = items[idx].value

    with console.status(t("[accent]Loading subtitle files...[/accent]"), spinner=theme.SPINNER):
        files = _list_files(entry.get("id"), key)
    files = [f for f in files if isinstance(f.get("name"), str) and f.get("url")]
    if not files:
        console.print(t("[warning]That series has no downloadable files — trying subliminal instead.[/warning]"))
        return None

    # Pick a file.
    file_items = []
    for f in files:
        size = f.get("size")
        hint = f"{int(size)/1024:.0f} KiB" if isinstance(size, (int, float)) and size else ""  # i18n: ignore — stable identity, source/tool data or public English value
        file_items.append(SelectItem(label=f["name"], value=f, is_action=True, hint=hint))
    file_items.append(SelectItem(label=t("Cancel"), value=None, is_action=True))
    idx = arrow_select(file_items, title=f"Jimaku › {escape(_entry_label(entry))}")  # i18n: ignore — stable identity, source/tool data or public English value
    if idx is None or file_items[idx].value is None:
        return None
    chosen = file_items[idx].value

    with console.status(t("[accent]Downloading {value}...[/accent]", value=escape(chosen['name'])), spinner=theme.SPINNER):
        saved = _download(chosen["url"], chosen["name"], key)
    if saved:
        console.print(t("\n[success]Saved Jimaku subtitle to {value}![/success]", value=escape(get_download_dir())))
    return saved


def is_subtitle_file(path: str) -> bool:
    """True if the path is a directly-usable subtitle (not e.g. a .zip)."""
    return path.lower().endswith(_SUB_EXTS)


def validate_key(key: str):
    """Check a Jimaku API key with a tiny search request.

    Returns ``(ok, message)`` where ``ok`` is True (valid), False (rejected —
    401), or None (couldn't verify — network/other).
    """
    try:
        resp = requests.get(
            f"{_BASE}/entries/search",
            params={"query": "test"},
            headers=_headers(key),
            timeout=15,
        )
        if resp.status_code == 401:
            return False, N_("Invalid API key (401)")
        resp.raise_for_status()
        return True, N_("API key accepted")
    except Exception as e:
        return None, f"Couldn't verify ({str(e)[:120] or type(e).__name__})"  # i18n: ignore — stable identity, source/tool data or public English value


def verification_label(message: str) -> str:
    """Display a verification message; validate_key keeps its public English result."""
    match = re.fullmatch(r"Couldn't verify \((.*)\)", message, re.S)  # i18n: ignore — public return value
    if match:
        return t("Couldn't verify ({error})", error=match[1])
    return t(message)
