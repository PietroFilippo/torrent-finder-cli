"""Explicit qBittorrent WebUI handoff and read-only client state (API v2)."""

from dataclasses import dataclass
import base64
import hashlib
import re
from urllib.parse import parse_qs, urlsplit

import requests

from torrent_finder import credentials
from torrent_finder.search_errors import SearchError


class ClientError(SearchError):
    """User-safe message; never includes the request or credential values."""


def configured():
    return bool(credentials.get_credential("QBITTORRENT_URL"))


def normalize_url(value):
    try:
        url = urlsplit(value.strip())
        port = url.port
        if (url.scheme not in {"http", "https"} or not url.hostname or url.username
                or url.password or url.query or url.fragment or (port is not None and port < 1)):
            raise ValueError()
        if any(c.isspace() for c in value):
            raise ValueError()
    except ValueError:
        raise ClientError("Use a WebUI http:// or https:// address, without embedded login, query or fragment.") from None
    return value.strip().rstrip("/")


@dataclass(frozen=True)
class TorrentPayload:
    info_hash: str
    magnet: str = ""
    data: bytes = b""


def magnet_payload(magnet):
    for xt in parse_qs(urlsplit(magnet).query).get("xt", []):
        if xt.lower().startswith("urn:btih:"):
            value = xt[9:]
            if re.fullmatch(r"[a-fA-F0-9]{40}", value):
                return TorrentPayload(value.lower(), magnet)
            if re.fullmatch(r"[A-Z2-7a-z]{32}", value):
                return TorrentPayload(base64.b32decode(value.upper()).hex(), magnet)
    raise ClientError("This listing has no usable BitTorrent v1 magnet hash.")


def torrent_payload(data):
    """Hash the original bencoded info bytes, without re-encoding dictionary keys."""
    if not isinstance(data, bytes) or not 0 < len(data) <= 8 * 1024 * 1024:
        raise ClientError("Invalid or oversized torrent metadata.")
    info_span = None

    def read(pos, depth=0):
        nonlocal info_span
        if depth > 64 or pos >= len(data):
            raise ValueError()
        start, kind = pos, data[pos:pos + 1]
        if kind in (b"d", b"l"):
            pos += 1
            values = {} if kind == b"d" else []
            while data[pos:pos + 1] != b"e":
                key, pos = read(pos, depth + 1)
                if kind == b"d":
                    if not isinstance(key, bytes) or key in values:
                        raise ValueError()
                    begin = pos
                    val, pos = read(pos, depth + 1)
                    values[key] = val
                    if depth == 0 and key == b"info":
                        info_span = (begin, pos)
                else:
                    values.append(key)
            return values, pos + 1
        if kind == b"i":
            end = data.index(b"e", pos)
            return int(data[pos + 1:end]), end + 1
        colon = data.index(b":", pos)
        length = int(data[start:colon])
        end = colon + 1 + length
        if length < 0 or end > len(data):
            raise ValueError()
        return data[colon + 1:end], end

    try:
        root, end = read(0)
        info = root[b"info"]
        if end != len(data) or not isinstance(info, dict) or info_span is None:
            raise ValueError()
        raw = data[info_span[0]:info_span[1]]
        if b"pieces" in info:
            info_hash = hashlib.sha1(raw).hexdigest()
        elif info.get(b"meta version") == 2:
            # qBittorrent identifies pure v2 torrents by the truncated v2 hash.
            info_hash = hashlib.sha256(raw).hexdigest()[:40]
        else:
            raise ValueError()
    except (ValueError, TypeError, KeyError, IndexError, RecursionError):
        raise ClientError("The source did not return valid torrent metadata.") from None
    return TorrentPayload(info_hash, data=data)


class Client:
    def __init__(self, url, username="", password="", session=None):
        self.url = normalize_url(url)
        self.username, self.password = username, password
        self.session = session or requests.Session()
        self.session.headers.update({"Referer": self.url + "/"})

    @classmethod
    def from_settings(cls):
        return cls(*(credentials.get_credential(k) or "" for k in
                     ("QBITTORRENT_URL", "QBITTORRENT_USERNAME", "QBITTORRENT_PASSWORD")))

    def close(self):
        self.session.close()

    def _request(self, method, endpoint, **kwargs):
        try:
            response = self.session.request(method, self.url + "/api/v2/" + endpoint,
                                            timeout=8, allow_redirects=False, **kwargs)
        except requests.RequestException:
            message = ("Submission outcome is unknown; refresh client progress before retrying."
                       if endpoint == "torrents/add" else "Cannot reach qBittorrent WebUI. Check its address and connection.")
            raise ClientError(message) from None
        if response.status_code in {401, 403}:
            raise ClientError("qBittorrent rejected access. Check the WebUI login, host restrictions or temporary IP ban.")
        if response.status_code != 200:
            raise ClientError(f"qBittorrent returned HTTP {response.status_code}. Check WebUI access and API compatibility.")
        return response

    def _json(self, endpoint, expected, **kwargs):
        try:
            value = self._request("GET", endpoint, **kwargs).json()
            if not isinstance(value, expected):
                raise ValueError()
            return value
        except ValueError:
            raise ClientError("qBittorrent returned an unexpected response; check the WebUI address.") from None

    def connect(self):
        if self.username or self.password:
            response = self._request("POST", "auth/login", data={"username": self.username, "password": self.password})
            if response.text.strip() != "Ok.":
                raise ClientError("qBittorrent login was rejected. Check username and password.")
        version = self._request("GET", "app/version").text.strip()
        if not re.fullmatch(r"v?\d+\.\d+(?:\.\d+)?[\w.\-+]*", version):
            raise ClientError("This address did not return a qBittorrent version.")
        return version

    def torrents(self, hashes=()):
        params = {"hashes": "|".join(hashes)} if hashes else {}
        rows = self._json("torrents/info", list, params=params)
        if any(not isinstance(r, dict) or not r.get("hash") for r in rows):
            raise ClientError("qBittorrent returned malformed torrent state.")
        return rows

    def categories(self):
        return self._json("torrents/categories", dict)

    def add(self, payload, save_path="", category=""):
        if self.torrents([payload.info_hash]):
            return "already in client"
        data = {"category": category, "autoTMM": "false"}
        if save_path:
            data["savepath"] = save_path
        files = None
        if payload.magnet:
            data["urls"] = payload.magnet
        else:
            files = {"torrents": ("selected.torrent", payload.data, "application/x-bittorrent")}
        response = self._request("POST", "torrents/add", data=data, files=files)
        if response.text.strip() != "Ok.":
            raise ClientError("qBittorrent did not accept this torrent. Check the client before retrying.")
        try:
            present = bool(self.torrents([payload.info_hash]))
        except ClientError:
            present = False
        return "added to client" if present else "submitted; confirmation pending"


def verify(values):
    client = None
    try:
        client = Client(values.get("QBITTORRENT_URL") or "", values.get("QBITTORRENT_USERNAME") or "",
                        values.get("QBITTORRENT_PASSWORD") or "")
        return True, "Connected to qBittorrent " + client.connect()
    except ClientError as error:
        return False, str(error)
    finally:
        if client:
            client.close()
