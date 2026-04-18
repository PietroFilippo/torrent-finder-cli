"""Fetch torrent file list from a magnet link using aria2c."""

import base64
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass


@dataclass
class TorrentFile:
    index: int  # 1-based (matches aria2 --select-file indexing)
    name: str
    size_bytes: int


@dataclass
class TorrentMetadata:
    name: str  # info.name — root folder (multi-file) or filename (single-file)
    files: list[TorrentFile]


def has_aria2() -> bool:
    return shutil.which("aria2c") is not None


def fetch_file_list(magnet: str, timeout: int = 120) -> TorrentMetadata | None:
    """Fetch torrent metadata via aria2c and return its file list.

    aria2c `--show-files` only operates on `.torrent` files, not magnets,
    so we run aria2c with `--bt-metadata-only` + `--bt-save-metadata`,
    which fetches metadata over DHT/peers, writes `<infohash>.torrent`,
    and exits. We then parse that file with a minimal bencode decoder —
    the file order in `info.files` is what aria2 uses for `--select-file`
    indexing (1-based).

    Returns None on missing aria2c, invalid magnet, timeout, or parse failure.
    """
    if not has_aria2():
        return None

    info_hash = _extract_info_hash(magnet)
    if not info_hash:
        return None

    with tempfile.TemporaryDirectory(prefix="tmeta_") as td:
        try:
            subprocess.run(
                [
                    "aria2c",
                    "--bt-metadata-only=true",
                    "--bt-save-metadata=true",
                    "--follow-torrent=false",
                    "--seed-time=0",
                    "--summary-interval=0",
                    "--console-log-level=warn",
                    "-d", td,
                    magnet,
                ],
                capture_output=True,
                timeout=timeout,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None

        torrent_path = os.path.join(td, f"{info_hash}.torrent")
        if not os.path.exists(torrent_path):
            return None

        try:
            with open(torrent_path, "rb") as f:
                data, _ = _bdecode(f.read(), 0)
        except Exception:
            return None

    return _metadata_from_torrent_dict(data)


def _extract_info_hash(magnet: str) -> str | None:
    """Pull the info hash from a magnet URI, returning lowercase hex (40 chars)."""
    m = re.search(r"urn:btih:([A-Fa-f0-9]{40}|[A-Za-z2-7]{32})", magnet)
    if not m:
        return None
    val = m.group(1)
    if len(val) == 32:  # base32 → hex
        try:
            return base64.b16encode(base64.b32decode(val.upper())).decode("ascii").lower()
        except Exception:
            return None
    return val.lower()


def _bdecode(data: bytes, pos: int):
    """Minimal bencode decoder. Returns (value, next_pos). Strings stay as bytes."""
    c = data[pos:pos + 1]
    if c == b"i":
        end = data.index(b"e", pos)
        return int(data[pos + 1:end]), end + 1
    if c == b"l":
        result = []
        pos += 1
        while data[pos:pos + 1] != b"e":
            val, pos = _bdecode(data, pos)
            result.append(val)
        return result, pos + 1
    if c == b"d":
        result = {}
        pos += 1
        while data[pos:pos + 1] != b"e":
            key, pos = _bdecode(data, pos)
            val, pos = _bdecode(data, pos)
            result[key] = val
        return result, pos + 1
    # byte-string: "<length>:<bytes>"
    colon = data.index(b":", pos)
    length = int(data[pos:colon])
    start = colon + 1
    return data[start:start + length], start + length


def _metadata_from_torrent_dict(data: dict) -> TorrentMetadata | None:
    info = data.get(b"info")
    if not isinstance(info, dict):
        return None
    name_raw = info.get(b"name", b"unknown")
    torrent_name = (
        name_raw.decode("utf-8", errors="replace") if isinstance(name_raw, bytes) else str(name_raw)
    )
    files: list[TorrentFile] = []
    multi = info.get(b"files")
    if isinstance(multi, list):
        for i, entry in enumerate(multi, 1):
            if not isinstance(entry, dict):
                continue
            parts = entry.get(b"path", [])
            path = "/".join(
                p.decode("utf-8", errors="replace") if isinstance(p, bytes) else str(p)
                for p in parts
            )
            length = entry.get(b"length", 0)
            files.append(TorrentFile(index=i, name=path, size_bytes=int(length)))
    else:
        length = info.get(b"length", 0)
        files.append(TorrentFile(index=1, name=torrent_name, size_bytes=int(length)))
    return TorrentMetadata(name=torrent_name, files=files)


def extract_episode_number(filename: str) -> str | None:
    """Best-effort extraction of an episode number from an anime filename."""
    basename = os.path.basename(filename)
    for pat in (
        r"[Ss]\d+[Ee](\d{1,4})",
        r" - (\d{1,4})(?:v\d+)?(?=\D)",
        r"\[(\d{1,4})(?:v\d+)?\]",
        r"Episode\s*(\d{1,4})",
    ):
        m = re.search(pat, basename, re.IGNORECASE)
        if m:
            return m.group(1).lstrip("0") or "0"
    return None


def format_size(size_bytes: int) -> str:
    for unit, factor in (("TB", 1024**4), ("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if size_bytes >= factor:
            return f"{size_bytes / factor:.2f} {unit}"
    return f"{size_bytes} B"


def compact_ranges(indexes: list[int]) -> str:
    """Convert a sorted list of ints into aria2c --select-file syntax (e.g. '1,3,5-7')."""
    if not indexes:
        return ""
    sorted_idx = sorted(set(indexes))
    ranges = []
    start = prev = sorted_idx[0]
    for n in sorted_idx[1:]:
        if n == prev + 1:
            prev = n
            continue
        ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
        start = prev = n
    ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
    return ",".join(ranges)
