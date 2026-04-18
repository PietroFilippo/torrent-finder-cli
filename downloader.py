"""Download methods: torrent client (magnet) and webtorrent direct download."""

import os
import platform
import re
import shutil
import subprocess
import threading
import time
import urllib.parse

from constants import DOWNLOADS_DIR, console
from torrent_meta import compact_ranges


def _resolve_vlc_path() -> str | None:
    vlc_path = shutil.which("vlc")
    if not vlc_path and platform.system() == "Windows":
        for p in [r"C:\Program Files\VideoLAN\VLC\vlc.exe", r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"]:
            if os.path.exists(p):
                return p
    return vlc_path


def _start_vlc_hotkey_thread(url_holder: list, advance_event: threading.Event | None = None) -> threading.Event:
    """Listen for 'v' (reopen VLC) and optionally 'n' (advance to next session).

    url_holder is a single-element list so callers can update the URL after
    capturing it from a subprocess's stdout. advance_event, when provided,
    is set on 'n' so the caller can terminate the current session and move on.
    """
    stop_event = threading.Event()

    def listener():
        vlc_path = _resolve_vlc_path()
        while not stop_event.is_set():
            if platform.system() == "Windows":
                import msvcrt
                if msvcrt.kbhit():
                    key = msvcrt.getch()
                    if key.lower() == b'v':
                        url = url_holder[0] if url_holder else None
                        if not url:
                            continue
                        if vlc_path:
                            subprocess.Popen([vlc_path, url])
                        else:
                            try:
                                os.startfile(url)
                            except Exception:
                                pass
                    elif key.lower() == b'n' and advance_event is not None:
                        advance_event.set()
            time.sleep(0.2)

    t = threading.Thread(target=listener, daemon=True)
    t.start()
    return stop_event


def detect_torrent_client() -> str:
    """Detect the installed torrent client.

    On Windows, scans common install directories first, then checks PATH, then the registry.
    """
    # Known torrent client executables and their names
    KNOWN_CLIENTS = {
        "qbittorrent": "qBittorrent",
        "utorrent": "uTorrent",
        "bittorrent": "BitTorrent",
        "deluge": "Deluge",
        "transmission-qt": "Transmission",
        "transmission-gtk": "Transmission",
        "vuze": "Vuze",
        "tixati": "Tixati",
        "biglybt": "BiglyBT",
    }

    # 1. Windows: scan common install directories
    if platform.system() == "Windows":
        search_dirs = [
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
        ]
        for search_dir in search_dirs:
            if not search_dir or not os.path.isdir(search_dir):
                continue
            try:
                for folder in os.listdir(search_dir):
                    folder_lower = folder.lower()
                    for key, name in KNOWN_CLIENTS.items():
                        if key in folder_lower:
                            return name
            except OSError:
                continue

    # 2. Check PATH
    for exe, name in KNOWN_CLIENTS.items():
        if shutil.which(exe):
            return name

    # 3. Windows fallback: read the registry magnet: handler
    if platform.system() == "Windows":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"magnet\shell\open\command") as key:
                cmd = winreg.QueryValueEx(key, "")[0]
                exe_match = re.search(r'([\w.-]+)\.exe', cmd, re.IGNORECASE)
                if exe_match:
                    exe_name = exe_match.group(1).lower()
                    for known_key, friendly_name in KNOWN_CLIENTS.items():
                        if known_key in exe_name:
                            return friendly_name
                    return exe_match.group(1).capitalize()
        except (OSError, ImportError):
            pass

    return "default torrent client"


def open_magnet(magnet_link: str) -> None:
    """Open a magnet link with the system default handler (qBittorrent, etc.)."""
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(magnet_link)
        elif system == "Darwin":
            subprocess.Popen(["open", magnet_link])
        else:
            subprocess.Popen(["xdg-open", magnet_link])
    except Exception as e:
        console.print(f"[error] Failed to open magnet link: {e}[/error]")
        console.print(f"[info]Magnet link:[/info] {magnet_link}")


def has_peerflix() -> bool:
    """Check if peerflix is installed."""
    return shutil.which("peerflix") is not None


def has_webtorrent() -> bool:
    """Check if webtorrent-cli is installed."""
    return shutil.which("webtorrent") is not None


def has_aria2() -> bool:
    """Check if aria2c is installed."""
    return shutil.which("aria2c") is not None


def download_with_aria2(magnet_link: str, select_indexes: list[int] | None = None) -> None:
    """Download torrent content using aria2c.

    Supports multi-file selection natively via --select-file=1,3,5-7 in a
    single process. select_indexes are 1-based (aria2's convention).
    """
    aria_path = shutil.which("aria2c")
    if not aria_path:
        console.print("[error] aria2c not found. Install from https://aria2.github.io/[/error]\n")
        return

    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    console.print(f"[info]Downloading to:[/info] [highlight]{DOWNLOADS_DIR}[/highlight]")
    if select_indexes:
        console.print(f"[info]Selected files:[/info] [highlight]{compact_ranges(select_indexes)}[/highlight] ({len(select_indexes)} file(s))")
    console.print("[bold red]To cancel, press CTRL+C at any time.[/bold red]\n")

    cmd = [
        aria_path,
        "-d", DOWNLOADS_DIR,
        "--seed-time=0",
        "--summary-interval=0",
        "--console-log-level=warn",
        "--bt-remove-unselected-file=true",
    ]
    if select_indexes:
        cmd.append(f"--select-file={compact_ranges(select_indexes)}")
    cmd.append(magnet_link)

    try:
        result = subprocess.run(cmd)
        console.print()
        if result.returncode == 0:
            console.print("[success] Download complete![/success]")
            console.print(f"[info]Files saved to:[/info] [highlight]{DOWNLOADS_DIR}[/highlight]\n")
        else:
            console.print(f"[error] Download failed (exit code {result.returncode}).[/error]\n")
    except KeyboardInterrupt:
        console.print("\n[warning] Download cancelled.[/warning]\n")
    except FileNotFoundError:
        console.print("[error] aria2c not found. Install from https://aria2.github.io/[/error]\n")


def download_with_webtorrent(magnet_link: str, select_indexes: list[int] | None = None) -> None:
    """Download torrent content directly using webtorrent-cli.

    Runs webtorrent in the terminal directly (no stdout piping) so its
    built-in progress UI renders natively. webtorrent-cli's --select takes a
    single file index (0-based); multi-file selection is handled by looping
    over the provided 1-based indexes.
    """
    wt_path = shutil.which("webtorrent")
    if not wt_path:
        console.print("[error] webtorrent-cli not found. Install with: npm install -g webtorrent-cli[/error]\n")
        return

    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    console.print(f"[info]Downloading to:[/info] [highlight]{DOWNLOADS_DIR}[/highlight]")
    if select_indexes and len(select_indexes) > 1:
        console.print(
            f"[warning] webtorrent-cli downloads one file at a time; "
            f"running {len(select_indexes)} sequential sessions. "
            f"Use aria2c for a single-process multi-file download.[/warning]"
        )
    console.print("[bold red]To cancel, press CTRL+C at any time.[/bold red]\n")

    targets: list[int | None] = [i for i in (select_indexes or [])] or [None]

    try:
        for n, idx in enumerate(targets, 1):
            if len(targets) > 1:
                console.print(f"[info]Session {n}/{len(targets)} — file index {idx}[/info]")
            cmd = [wt_path, "download", magnet_link, "--out", DOWNLOADS_DIR]
            if idx is not None:
                cmd.extend(["--select", str(idx - 1)])  # webtorrent is 0-based
            result = subprocess.run(cmd)
            if result.returncode != 0:
                console.print(f"[error] Session {n} failed (exit code {result.returncode}).[/error]\n")
                break

        console.print()
        console.print("[success] Download complete![/success]")
        console.print(f"[info]Files saved to:[/info] [highlight]{DOWNLOADS_DIR}[/highlight]\n")

    except KeyboardInterrupt:
        console.print("\n[warning] Download cancelled.[/warning]\n")
    except FileNotFoundError:
        console.print("[error] webtorrent-cli not found. Install with: npm install -g webtorrent-cli[/error]\n")


def download_with_peerflix(magnet_link: str, select_indexes: list[int] | None = None) -> None:
    """Download torrent content directly using peerflix.

    peerflix streams/downloads a single file per process; multi-file selection
    is handled by looping over the provided 1-based indexes. Use aria2c for a
    single-process multi-file download.
    """
    pf_path = shutil.which("peerflix")
    if not pf_path:
        console.print("[error] peerflix not found. Install with: npm install -g peerflix[/error]\n")
        return

    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    console.print(f"[info]Downloading to:[/info] [highlight]{DOWNLOADS_DIR}[/highlight]")
    if select_indexes and len(select_indexes) > 1:
        console.print(
            f"[warning] peerflix handles one file at a time; "
            f"running {len(select_indexes)} sequential sessions. "
            f"Use aria2c for a single-process multi-file download.[/warning]"
        )
    console.print("[bold red]To cancel, press CTRL+C at any time.[/bold red]\n")

    targets: list[int | None] = [i for i in (select_indexes or [])] or [None]

    try:
        for n, idx in enumerate(targets, 1):
            if len(targets) > 1:
                console.print(f"[info]Session {n}/{len(targets)} — file index {idx}[/info]")
            cmd = [pf_path, magnet_link, "--path", DOWNLOADS_DIR]
            if idx is not None:
                cmd.extend(["-i", str(idx - 1)])  # peerflix is 0-based
            result = subprocess.run(cmd)
            if result.returncode != 0:
                console.print(f"[error] Session {n} failed (exit code {result.returncode}).[/error]\n")
                break

        console.print()
        console.print("[success] Download complete![/success]")
        console.print(f"[info]Files saved to:[/info] [highlight]{DOWNLOADS_DIR}[/highlight]\n")

    except KeyboardInterrupt:
        console.print("\n[warning] Download cancelled.[/warning]\n")
    except FileNotFoundError:
        console.print("[error] peerflix not found. Install with: npm install -g peerflix[/error]\n")


def _run_stream(
    cmd: list[str],
    vlc_url: str | None,
    allow_advance: bool,
) -> tuple[int, bool]:
    """Run a streaming subprocess with native TTY (no stdout piping).

    vlc_url, if provided, is what the 'v' hotkey will relaunch VLC with.
    When allow_advance is True, 'n' terminates the subprocess so the caller
    can advance to the next session (multi-ep flow). Returns (returncode,
    advanced) — advanced=True means the user explicitly pressed 'n'.
    """
    url_holder: list[str | None] = [vlc_url]
    advance_event = threading.Event() if allow_advance else None
    stop_event = _start_vlc_hotkey_thread(url_holder, advance_event)

    proc = subprocess.Popen(cmd)
    advanced = False
    try:
        while proc.poll() is None:
            if advance_event is not None and advance_event.is_set():
                advanced = True
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                break
            time.sleep(0.25)
    except KeyboardInterrupt:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        raise
    finally:
        stop_event.set()
    return proc.returncode or 0, advanced


def _extract_infohash(magnet_link: str) -> str:
    m = re.search(r"urn:btih:([A-Fa-f0-9]{40}|[A-Za-z2-7]{32})", magnet_link)
    if not m:
        return ""
    val = m.group(1)
    if len(val) == 32:
        import base64
        try:
            return base64.b16encode(base64.b32decode(val.upper())).decode("ascii").lower()
        except Exception:
            return ""
    return val.lower()


def _magnet_dn(magnet_link: str) -> str | None:
    m = re.search(r"[?&]dn=([^&]+)", magnet_link)
    return urllib.parse.unquote_plus(m.group(1)) if m else None


def _webtorrent_vlc_url(
    magnet_link: str,
    torrent_name: str | None,
    file_path: str | None,
    is_multi_file: bool,
    port: int = 8080,
) -> str | None:
    """Reconstruct the URL webtorrent-cli serves the streamed file at.

    webtorrent-cli v5 serves via paths
      multi-file:  /webtorrent/<infohash>/<torrent_name>/<relative_path>
      single-file: /webtorrent/<infohash>/<torrent_name>
    torrent_name should come from the decoded bencoded `info.name` when
    available (authoritative); falls back to the magnet's `dn` otherwise.
    Returns None when key pieces are missing.
    """
    info_hash = _extract_infohash(magnet_link)
    if not info_hash:
        return None
    name = torrent_name or _magnet_dn(magnet_link)
    if not name:
        return None
    encoded_torrent = urllib.parse.quote(name, safe="[]()~")
    base = f"http://127.0.0.1:{port}/webtorrent/{info_hash}/{encoded_torrent}"
    if is_multi_file and file_path:
        encoded_file = urllib.parse.quote(file_path, safe="/[]()~")
        return f"{base}/{encoded_file}"
    return base


def stream_with_webtorrent(
    magnet_link: str,
    select_indexes: list[int] | None = None,
    files=None,  # TorrentMetadata | None
) -> None:
    """Stream selected files to VLC using webtorrent-cli.

    `files` is a TorrentMetadata whose .name (info.name) gives the exact
    torrent root for 'v' hotkey URL reconstruction, and whose .files list
    maps 1-based indexes to internal file paths.
    """
    wt_path = shutil.which("webtorrent")
    if not wt_path:
        console.print("[error] webtorrent-cli not found. Install with: npm install -g webtorrent-cli[/error]\n")
        return

    targets: list[int | None] = list(select_indexes) if select_indexes else [None]
    multi = len(targets) > 1
    file_list = files.files if files is not None else []
    name_by_idx = {f.index: f.name for f in file_list}
    is_multi_file = len(file_list) > 1
    torrent_name = files.name if files is not None else None

    try:
        for n, idx in enumerate(targets, 1):
            file_path = name_by_idx.get(idx) if idx is not None else None
            vlc_url = _webtorrent_vlc_url(magnet_link, torrent_name, file_path, is_multi_file)

            if multi:
                console.print(f"[info]Session {n}/{len(targets)} — file index {idx}[/info]")
            elif idx is not None:
                console.print(f"[info]Streaming file index:[/info] [highlight]{idx}[/highlight]")
            console.print("[bold red]CTRL+C to cancel.[/bold red]")
            if vlc_url:
                console.print("[bold yellow]Tip: Press 'v' to reopen VLC without losing download progress![/bold yellow]")
            if multi:
                console.print("[bold yellow]Press 'n' to skip to the next episode.[/bold yellow]")
            console.print()

            cmd = [wt_path, "download", magnet_link, "--vlc", "--no-quit", "--port", "8080"]
            if idx is not None:
                cmd.extend(["--select", str(idx - 1)])

            rc, advanced = _run_stream(cmd, vlc_url, allow_advance=multi)
            console.print()
            if not advanced:
                # Subprocess exited on its own (VLC close in --no-quit kept it
                # running, so this means webtorrent actually died — cancel).
                break

        console.print("[success] Streaming session(s) ended![/success]")
    except KeyboardInterrupt:
        console.print("\n[warning] Streaming cancelled.[/warning]\n")
    except FileNotFoundError:
        console.print("[error] webtorrent-cli not found. Install with: npm install -g webtorrent-cli[/error]\n")


def stream_with_peerflix(
    magnet_link: str,
    select_indexes: list[int] | None = None,
    files: list | None = None,
) -> None:
    """Stream selected files to VLC using peerflix.

    One session per selected 1-based index. peerflix serves the currently
    streaming file at the server root, so the 'v' hotkey URL is fixed.
    """
    pf_path = shutil.which("peerflix")
    if not pf_path:
        console.print("[error] peerflix not found. Install with: npm install -g peerflix[/error]\n")
        return

    targets: list[int | None] = list(select_indexes) if select_indexes else [None]
    multi = len(targets) > 1
    vlc_url = "http://127.0.0.1:8888/"
    _ = files  # kept for API symmetry with stream_with_webtorrent

    try:
        for n, idx in enumerate(targets, 1):
            if multi:
                console.print(f"[info]Session {n}/{len(targets)} — file index {idx}[/info]")
            elif idx is not None:
                console.print(f"[info]Streaming file index:[/info] [highlight]{idx}[/highlight]")
            console.print("[bold red]CTRL+C to cancel.[/bold red]")
            console.print("[bold yellow]Tip: Press 'v' to reopen VLC without losing download progress![/bold yellow]")
            if multi:
                console.print("[bold yellow]Press 'n' to skip to the next episode.[/bold yellow]")
            console.print()

            cmd = [pf_path, magnet_link, "--vlc", "--port", "8888"]
            if idx is not None:
                cmd.extend(["-i", str(idx - 1)])

            rc, advanced = _run_stream(cmd, vlc_url, allow_advance=multi)
            console.print()
            if not advanced:
                break

        console.print("[success] Streaming session(s) ended![/success]")
    except KeyboardInterrupt:
        console.print("\n[warning] Streaming cancelled.[/warning]\n")
    except FileNotFoundError:
        console.print("[error] peerflix not found. Install with: npm install -g peerflix[/error]\n")
