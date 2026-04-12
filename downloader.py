"""Download methods: torrent client (magnet) and webtorrent direct download."""

import os
import platform
import re
import shutil
import subprocess
import threading
import time

from constants import DOWNLOADS_DIR, console


def _start_vlc_hotkey_thread(stream_url: str) -> threading.Event:
    """Start a background thread to listen for the 'v' key and reopen VLC while a stream is running."""
    stop_event = threading.Event()

    def listener():
        vlc_path = shutil.which("vlc")
        if not vlc_path and platform.system() == "Windows":
            for p in [r"C:\Program Files\VideoLAN\VLC\vlc.exe", r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"]:
                if os.path.exists(p):
                    vlc_path = p
                    break

        while not stop_event.is_set():
            if platform.system() == "Windows":
                import msvcrt
                if msvcrt.kbhit():
                    key = msvcrt.getch()
                    if key.lower() == b'v':
                        if vlc_path:
                            subprocess.Popen([vlc_path, stream_url])
                        else:
                            os.startfile(stream_url)
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


def download_with_webtorrent(magnet_link: str) -> None:
    """Download torrent content directly using webtorrent-cli.

    Runs webtorrent in the terminal directly (no stdout piping) so its
    built-in progress UI renders natively. webtorrent-cli uses console.clear()
    and full-screen redraws with ANSI codes, which cannot be parsed via pipe.
    """
    wt_path = shutil.which("webtorrent")
    if not wt_path:
        console.print("[error] webtorrent-cli not found. Install with: npm install -g webtorrent-cli[/error]\n")
        return

    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    console.print(f"[info]Downloading to:[/info] [highlight]{DOWNLOADS_DIR}[/highlight]")
    console.print("[bold red]To cancel, press CTRL+C at any time.[/bold red]\n")

    try:
        result = subprocess.run(
            [wt_path, "download", magnet_link, "--out", DOWNLOADS_DIR],
        )

        console.print()
        if result.returncode == 0:
            console.print("[success] Download complete![/success]")
            console.print(f"[info]Files saved to:[/info] [highlight]{DOWNLOADS_DIR}[/highlight]\n")
        else:
            console.print(f"[error] Download failed (exit code {result.returncode}).[/error]\n")

    except KeyboardInterrupt:
        console.print("\n[warning] Download cancelled.[/warning]\n")
    except FileNotFoundError:
        console.print("[error] webtorrent-cli not found. Install with: npm install -g webtorrent-cli[/error]\n")


def download_with_peerflix(magnet_link: str) -> None:
    """Download torrent content directly using peerflix.

    Runs peerflix in the terminal directly (no stdout piping) so its
    built-in progress UI renders natively.
    """
    pf_path = shutil.which("peerflix")
    if not pf_path:
        console.print("[error] peerflix not found. Install with: npm install -g peerflix[/error]\n")
        return

    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    console.print(f"[info]Downloading to:[/info] [highlight]{DOWNLOADS_DIR}[/highlight]")
    console.print("[bold red]To cancel, press CTRL+C at any time.[/bold red]\n")

    try:
        result = subprocess.run(
            [pf_path, magnet_link, "--path", DOWNLOADS_DIR],
        )

        console.print()
        if result.returncode == 0:
            console.print("[success] Download complete![/success]")
            console.print(f"[info]Files saved to:[/info] [highlight]{DOWNLOADS_DIR}[/highlight]\n")
        else:
            console.print(f"[error] Download failed (exit code {result.returncode}).[/error]\n")

    except KeyboardInterrupt:
        console.print("\n[warning] Download cancelled.[/warning]\n")
    except FileNotFoundError:
        console.print("[error] peerflix not found. Install with: npm install -g peerflix[/error]\n")


def stream_with_webtorrent(magnet_link: str) -> None:
    """Stream torrent content directly to VLC using webtorrent-cli."""
    wt_path = shutil.which("webtorrent")
    if not wt_path:
        console.print("[error] webtorrent-cli not found. Install with: npm install -g webtorrent-cli[/error]\n")
        return

    console.print("[info]Starting streaming server and waiting for VLC to open...[/info]")
    console.print("[bold red]To cancel, press CTRL+C at any time.[/bold red]")
    console.print("[bold yellow]Tip: Press 'v' at any time to reopen VLC without losing download progress![/bold yellow]\n")

    try:
        stop_event = _start_vlc_hotkey_thread("http://127.0.0.1:8080/0")
        result = subprocess.run(
            [wt_path, "download", magnet_link, "--vlc", "--no-quit", "--port", "8080"],
        )
        stop_event.set()

        console.print()
        if result.returncode == 0:
            console.print("[success] Streaming session ended![/success]")
        else:
            console.print(f"[error] Streaming failed (exit code {result.returncode}).[/error]\n")

    except KeyboardInterrupt:
        console.print("\n[warning] Streaming cancelled.[/warning]\n")
    except FileNotFoundError:
        console.print("[error] webtorrent-cli not found. Install with: npm install -g webtorrent-cli[/error]\n")


def stream_with_peerflix(magnet_link: str) -> None:
    """Stream torrent content directly to VLC using peerflix."""
    pf_path = shutil.which("peerflix")
    if not pf_path:
        console.print("[error] peerflix not found. Install with: npm install -g peerflix[/error]\n")
        return

    console.print("[info]Starting streaming server and waiting for VLC to open...[/info]")
    console.print("[bold red]To cancel, press CTRL+C at any time.[/bold red]")
    console.print("[bold yellow]Tip: Press 'v' at any time to reopen VLC without losing download progress![/bold yellow]\n")

    try:
        stop_event = _start_vlc_hotkey_thread("http://127.0.0.1:8888/")
        result = subprocess.run(
            [pf_path, magnet_link, "--vlc", "--remove", "--port", "8888"],
        )
        stop_event.set()

        console.print()
        if result.returncode == 0:
            console.print("[success] Streaming session ended![/success]")
        else:
            console.print(f"[error] Streaming failed (exit code {result.returncode}).[/error]\n")

    except KeyboardInterrupt:
        console.print("\n[warning] Streaming cancelled.[/warning]\n")
    except FileNotFoundError:
        console.print("[error] peerflix not found. Install with: npm install -g peerflix[/error]\n")
