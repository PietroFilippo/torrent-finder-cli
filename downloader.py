"""Download methods: torrent client (magnet) and webtorrent direct download."""

import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse

from constants import DOWNLOADS_DIR, console
from state import load_setting
from torrent_meta import compact_ranges


_QUIET_SETTING_KEY = "hide_stream_output"


def is_quiet_mode() -> bool:
    """Read the persistent quiet-mode flag (suppress subprocess UI)."""
    return bool(load_setting(_QUIET_SETTING_KEY, False))


def _quiet_streams(quiet: bool) -> tuple[int | None, int | None]:
    """Map the quiet flag to subprocess stdout/stderr args.

    When quiet is True, returns (DEVNULL, DEVNULL) so the child's full-screen
    progress UI is fully suppressed. When False, returns (None, None) so the
    child inherits the parent TTY and renders natively.
    """
    if quiet:
        return subprocess.DEVNULL, subprocess.DEVNULL
    return None, None


def _resolve_vlc_path() -> str | None:
    vlc_path = shutil.which("vlc")
    if not vlc_path and platform.system() == "Windows":
        for p in [r"C:\Program Files\VideoLAN\VLC\vlc.exe", r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"]:
            if os.path.exists(p):
                return p
    return vlc_path


def _vlc_running() -> bool:
    """Return True if any VLC process is currently running."""
    system = platform.system()
    try:
        if system == "Windows":
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq vlc.exe", "/NH"],
                capture_output=True, text=True, timeout=2,
            )
            return "vlc.exe" in r.stdout.lower()
        elif system == "Darwin":
            r = subprocess.run(
                ["pgrep", "-x", "VLC"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
            )
            return r.returncode == 0
        else:
            r = subprocess.run(
                ["pgrep", "-x", "vlc"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
            )
            return r.returncode == 0
    except Exception:
        return False


def _kill_vlc() -> None:
    """Terminate all running VLC instances."""
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.run(
                ["taskkill", "/IM", "vlc.exe", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif system == "Darwin":
            subprocess.run(
                ["pkill", "-f", "VLC"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.run(
                ["pkill", "vlc"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception:
        pass


def _start_vlc_hotkey_thread(
    url_holder: list,
    advance_event: threading.Event | None = None,
    back_event: threading.Event | None = None,
) -> threading.Event:
    """Listen for 'v' (reopen VLC), 'n' (next episode), and 'b' (previous episode).

    url_holder is a single-element list so callers can update the URL after
    capturing it from a subprocess's stdout. advance_event, when provided,
    is set on 'n' so the caller can terminate the current session and move on.
    back_event, when provided, is set on 'b' to go back to the previous episode.
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
                        # Skip relaunch if VLC already running — avoids spawning duplicates
                        if _vlc_running():
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
                    elif key.lower() == b'b' and back_event is not None:
                        back_event.set()
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


def download_with_aria2(magnet_link: str, select_indexes: list[int] | None = None) -> bool:
    """Download torrent content using aria2c.

    Supports multi-file selection natively via --select-file=1,3,5-7 in a
    single process. select_indexes are 1-based (aria2's convention). Returns
    True on normal completion; False on cancellation or failure so callers
    can return the user to the download-method menu.
    """
    aria_path = shutil.which("aria2c")
    if not aria_path:
        console.print("[error] aria2c not found. Install from https://aria2.github.io/[/error]\n")
        return False

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
        # --file-allocation=none skips pre-allocating unselected files so
        # `--select-file` really gives you just what you picked on disk.
        cmd.append(f"--select-file={compact_ranges(select_indexes)}")
        cmd.append("--file-allocation=none")
    cmd.append(magnet_link)

    quiet = is_quiet_mode()

    try:
        if quiet:
            with console.status(
                "[bold cyan]Downloading…[/bold cyan]  Ctrl+C cancel",
                spinner="dots",
            ):
                result = subprocess.run(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
        else:
            result = subprocess.run(cmd)
        console.print()
        if result.returncode == 0:
            console.print("[success] Download complete![/success]")
            console.print(f"[info]Files saved to:[/info] [highlight]{DOWNLOADS_DIR}[/highlight]\n")
            return True
        console.print(f"[error] Download failed (exit code {result.returncode}).[/error]\n")
        return False
    except KeyboardInterrupt:
        console.print("\n[warning] Download cancelled.[/warning]\n")
        return False
    except FileNotFoundError:
        console.print("[error] aria2c not found. Install from https://aria2.github.io/[/error]\n")
        return False


def download_with_webtorrent(magnet_link: str, select_indexes: list[int] | None = None) -> bool:
    """Download torrent content directly using webtorrent-cli.

    Runs webtorrent in the terminal directly (no stdout piping) so its
    built-in progress UI renders natively. webtorrent-cli's --select takes a
    single file index (0-based); multi-file selection is handled by looping
    over the provided 1-based indexes. Returns True on normal completion;
    False on cancellation or failure.
    """
    wt_path = shutil.which("webtorrent")
    if not wt_path:
        console.print("[error] webtorrent-cli not found. Install with: npm install -g webtorrent-cli[/error]\n")
        return False

    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    console.print(f"[info]Downloading to:[/info] [highlight]{DOWNLOADS_DIR}[/highlight]")
    if select_indexes:
        console.print(
            "[warning] webtorrent-cli's --select does NOT always limit download to the picked "
            "file(s) — it can still pull the whole torrent. "
            "Use [bold]aria2c[/bold] for strict file selection.[/warning]"
        )
        if len(select_indexes) > 1:
            console.print(
                f"[warning] Running {len(select_indexes)} sequential sessions "
                "(webtorrent-cli downloads one file per run).[/warning]"
            )
    console.print("[bold red]To cancel, press CTRL+C at any time.[/bold red]\n")

    targets: list[int | None] = [i for i in (select_indexes or [])] or [None]
    quiet = is_quiet_mode()

    try:
        for n, idx in enumerate(targets, 1):
            if len(targets) > 1:
                console.print(f"[info]Session {n}/{len(targets)} — file index {idx}[/info]")
            cmd = [wt_path, "download", magnet_link, "--out", DOWNLOADS_DIR]
            if idx is not None:
                cmd.extend(["--select", str(idx - 1)])  # webtorrent is 0-based
            if quiet:
                with console.status(
                    f"[bold cyan]Downloading…[/bold cyan]  "
                    f"{'session ' + str(n) + '/' + str(len(targets)) + '  •  ' if len(targets) > 1 else ''}"
                    "Ctrl+C cancel",
                    spinner="dots",
                ):
                    result = subprocess.run(
                        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
            else:
                result = subprocess.run(cmd)
            if result.returncode != 0:
                console.print(f"\n[error] Session {n} failed (exit code {result.returncode}).[/error]\n")
                return False

        console.print()
        console.print("[success] Download complete![/success]")
        console.print(f"[info]Files saved to:[/info] [highlight]{DOWNLOADS_DIR}[/highlight]\n")
        return True

    except KeyboardInterrupt:
        console.print("\n[warning] Download cancelled.[/warning]\n")
        return False
    except FileNotFoundError:
        console.print("[error] webtorrent-cli not found. Install with: npm install -g webtorrent-cli[/error]\n")
        return False


def download_with_peerflix(magnet_link: str, select_indexes: list[int] | None = None) -> bool:
    """Download torrent content directly using peerflix.

    peerflix streams/downloads a single file per process; multi-file selection
    is handled by looping over the provided 1-based indexes. Use aria2c for a
    single-process multi-file download. Returns True on normal completion;
    False on cancellation or failure.
    """
    pf_path = shutil.which("peerflix")
    if not pf_path:
        console.print("[error] peerflix not found. Install with: npm install -g peerflix[/error]\n")
        return False

    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    console.print(f"[info]Downloading to:[/info] [highlight]{DOWNLOADS_DIR}[/highlight]")
    if select_indexes:
        console.print(
            "[warning] peerflix is a streaming tool — its -i flag only picks which file is "
            "served at the root, NOT which pieces are downloaded. The whole torrent will "
            "still be pulled to disk. Use [bold]aria2c[/bold] for strict file selection.[/warning]"
        )
        if len(select_indexes) > 1:
            console.print(
                f"[warning] Running {len(select_indexes)} sequential sessions "
                "(peerflix handles one file per run).[/warning]"
            )
    console.print("[bold red]To cancel, press CTRL+C at any time.[/bold red]\n")

    targets: list[int | None] = [i for i in (select_indexes or [])] or [None]
    quiet = is_quiet_mode()

    try:
        for n, idx in enumerate(targets, 1):
            if len(targets) > 1:
                console.print(f"[info]Session {n}/{len(targets)} — file index {idx}[/info]")
            cmd = [pf_path, magnet_link, "--path", DOWNLOADS_DIR]
            if idx is not None:
                cmd.extend(["-i", str(idx - 1)])  # peerflix is 0-based
            if quiet:
                with console.status(
                    f"[bold cyan]Downloading…[/bold cyan]  "
                    f"{'session ' + str(n) + '/' + str(len(targets)) + '  •  ' if len(targets) > 1 else ''}"
                    "Ctrl+C cancel",
                    spinner="dots",
                ):
                    result = subprocess.run(
                        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
            else:
                result = subprocess.run(cmd)
            if result.returncode != 0:
                console.print(f"\n[error] Session {n} failed (exit code {result.returncode}).[/error]\n")
                return False

        console.print()
        console.print("[success] Download complete![/success]")
        console.print(f"[info]Files saved to:[/info] [highlight]{DOWNLOADS_DIR}[/highlight]\n")
        return True

    except KeyboardInterrupt:
        console.print("\n[warning] Download cancelled.[/warning]\n")
        return False
    except FileNotFoundError:
        console.print("[error] peerflix not found. Install with: npm install -g peerflix[/error]\n")
        return False


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill a subprocess and all its children.

    On Windows, ``proc.terminate()`` only kills the parent process — child
    processes (e.g. peerflix spawns node children for streaming) keep running.
    Using ``taskkill /T`` (tree kill) ensures the entire process tree dies.
    """
    pid = proc.pid
    if platform.system() == "Windows":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        # On Unix, kill the process group
        try:
            import signal
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _run_stream(
    cmd: list[str],
    vlc_url: str | None,
    allow_navigate: bool,
    quiet: bool = False,
) -> tuple[int, str]:
    """Run a streaming subprocess with native TTY (no stdout piping).

    vlc_url, if provided, is what the 'v' hotkey will relaunch VLC with.
    When allow_navigate is True, 'n'/'b' terminate the subprocess so the
    caller can advance or go back in a multi-ep flow. Returns (returncode,
    nav_action) where nav_action is 'next', 'back', or 'none'.

    When quiet is True, subprocess stdout/stderr are redirected to DEVNULL
    (full-screen UI suppressed) and a rich spinner renders in its place.
    """
    url_holder: list[str | None] = [vlc_url]
    advance_event = threading.Event() if allow_navigate else None
    back_event = threading.Event() if allow_navigate else None
    stop_event = _start_vlc_hotkey_thread(url_holder, advance_event, back_event)

    stdout_arg, stderr_arg = _quiet_streams(quiet)
    proc = subprocess.Popen(cmd, stdout=stdout_arg, stderr=stderr_arg)
    nav_action = "none"

    def _poll_loop() -> str:
        while proc.poll() is None:
            if advance_event is not None and advance_event.is_set():
                _kill_process_tree(proc)
                return "next"
            if back_event is not None and back_event.is_set():
                _kill_process_tree(proc)
                return "back"
            time.sleep(0.25)
        return "none"

    try:
        if quiet:
            hints = ["Ctrl+C cancel"]
            if vlc_url:
                hints.append("v reopen VLC")
            if allow_navigate:
                hints.append("n/b next/prev")
            msg = "[bold cyan]Streaming…[/bold cyan]  " + "  •  ".join(hints)
            with console.status(msg, spinner="dots"):
                nav_action = _poll_loop()
        else:
            nav_action = _poll_loop()
    except KeyboardInterrupt:
        if proc.poll() is None:
            _kill_process_tree(proc)
        raise
    finally:
        stop_event.set()
    return proc.returncode or 0, nav_action


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
        
    if not is_multi_file and file_path:
        # For single files, webtorrent's torrent.name IS the full filename
        # (e.g. 'Movie.mkv' instead of just 'Movie'). webtorrent serves it at:
        # /webtorrent/<infohash>/<filename>
        name = file_path
    else:
        name = torrent_name or _magnet_dn(magnet_link)
        
    if not name:
        return None
        
    encoded_torrent = urllib.parse.quote(name, safe="()~")
    base = f"http://127.0.0.1:{port}/webtorrent/{info_hash}/{encoded_torrent}"
    if is_multi_file and file_path:
        encoded_file = urllib.parse.quote(file_path, safe="/()~")
        return f"{base}/{encoded_file}"
    return base


# Fixed header height for multi-episode streaming.  We always reserve this
# many lines so the scroll region boundary never shifts between episodes.
_STREAM_HEADER_LINES = 7


def _clear_terminal() -> None:
    """Clear the terminal screen."""
    os.system('cls' if os.name == 'nt' else 'clear')


def _set_terminal_title(title: str) -> None:
    """Set the terminal window title via OSC escape."""
    sys.stdout.write(f"\033]0;{title}\007")
    sys.stdout.flush()


def _print_stream_header(
    ep_idx: int,
    total: int,
    file_idx: int | None,
    multi: bool,
    vlc_url: str | None = None,
    use_scroll_region: bool = True,
) -> None:
    """Print the episode header and optionally pin it with a scroll region.

    When *use_scroll_region* is True (peerflix), the header is pinned at
    the top of the terminal and a scroll region is set below it.
    When False (webtorrent), only the terminal **window title** is used
    for persistent episode info, since webtorrent's ANSI rendering
    clears through scroll regions.
    """
    # Reset any previous scroll region so clear works on the full screen
    sys.stdout.write("\033[r")
    sys.stdout.flush()
    _clear_terminal()

    n = ep_idx + 1

    # Always set the terminal title — persists regardless of screen content
    if multi:
        _set_terminal_title(f"Episode {n}/{total} — file {file_idx} | n: next  b: back  v: VLC  Ctrl+C: cancel")
    elif file_idx is not None:
        _set_terminal_title(f"Streaming file {file_idx} | v: VLC  Ctrl+C: cancel")

    # Build header lines
    lines: list[str] = []
    if multi:
        lines.append(f"[info]Episode {n}/{total} \u2014 file index {file_idx}[/info]")
    elif file_idx is not None:
        lines.append(f"[info]Streaming file index:[/info] [highlight]{file_idx}[/highlight]")
    lines.append("[bold red]CTRL+C to cancel.[/bold red]")
    if vlc_url:
        lines.append("[bold yellow]Press 'v' to reopen VLC without losing download progress.[/bold yellow]")
    if multi:
        lines.append("[bold yellow]Press 'n' to skip to the next episode.[/bold yellow]")
        if ep_idx > 0:
            lines.append("[bold yellow]Press 'b' to go back to the previous episode (will re-download).[/bold yellow]")
        lines.append("[dim]VLC will be closed automatically when switching episodes.[/dim]")

    # Print the header lines
    for line in lines:
        console.print(line)

    if use_scroll_region:
        # Pad to fixed height so the scroll region boundary is stable
        for _ in range(len(lines), _STREAM_HEADER_LINES):
            console.print()
        # Set scroll region: rows _STREAM_HEADER_LINES+1 .. terminal height
        term_h = console.size.height
        top = _STREAM_HEADER_LINES + 1
        if top < term_h:
            sys.stdout.write(f"\033[{top};{term_h}r")
            # Move cursor into the scroll region and clear it
            sys.stdout.write(f"\033[{top};1H")
            sys.stdout.write("\033[J")  # erase from cursor to end of region
            sys.stdout.flush()
    else:
        console.print()  # just a blank separator line


def _reset_scroll_region() -> None:
    """Remove the scroll region so the full terminal is usable again."""
    sys.stdout.write("\033[r")
    sys.stdout.flush()


def _reset_terminal_title() -> None:
    """Restore the terminal title to the default."""
    _set_terminal_title("Torrent Search CLI")


def stream_with_webtorrent(
    magnet_link: str,
    select_indexes: list[int] | None = None,
    files=None,  # TorrentMetadata | None
) -> None:
    """Stream selected files to VLC using webtorrent-cli.

    `files` is a TorrentMetadata whose .name (info.name) gives the exact
    torrent root for 'v' hotkey URL reconstruction, and whose .files list
    maps 1-based indexes to internal file paths.

    webtorrent-cli uses full-screen ANSI rendering (``\033[2J``) that
    clears through scroll regions, so we use the terminal window title
    for persistent episode info instead.
    """
    wt_path = shutil.which("webtorrent")
    if not wt_path:
        console.print("[error] webtorrent-cli not found. Install with: npm install -g webtorrent-cli[/error]\n")
        return

    from torrent_meta import fetch_file_list, is_multi_episode, sort_episodes, video_files

    if files is None:
        console.print("[info]Fetching metadata to resolve exact stream URL...[/info]")
        with console.status("[bold cyan]Fetching metadata...", spinner="dots"):
            files = fetch_file_list(magnet_link)

    targets: list[int | None] = list(select_indexes) if select_indexes else []
    file_list = files.files if files is not None else []

    if targets and file_list:
        # User-supplied selection may include non-video files (artwork, .nfo,
        # subs). Stream only the playable ones, warn about the rest. If the
        # selection is *entirely* non-video, respect the user's pick and bail
        # — don't silently substitute a video they didn't choose.
        video_idxs = {f.index for f in video_files(file_list)}
        filtered = [i for i in targets if i in video_idxs]
        skipped = len(targets) - len(filtered)
        if skipped and filtered:
            console.print(
                f"[warning] Skipping {skipped} non-video file(s) — streamable files only.[/warning]"
            )
        if not filtered:
            console.print(
                "[error] Selection contains no streamable video files. "
                "Pick a video file or use a download method instead.[/error]\n"
            )
            return
        targets = filtered

    if not targets and file_list:
        if is_multi_episode(file_list):
            # Multi-episode release — queue every video file in episode order so
            # `n`/`b` navigation works even without an explicit picker selection.
            targets = [f.index for f in sort_episodes(file_list)]
        else:
            # Single-episode / movie — webtorrent defaults to the largest file;
            # resolve it explicitly so the VLC URL reconstruction matches.
            largest_file = max(file_list, key=lambda f: f.size_bytes)
            targets = [largest_file.index]
    elif not targets:
        # Fallback if there are no metadata
        targets = [None]
        
    multi = len(targets) > 1
    name_by_idx = {f.index: f.name for f in file_list}
    is_multi_file = len(file_list) > 1
    torrent_name = files.name if files is not None else None
    quiet = is_quiet_mode()

    try:
        ep_idx = 0
        while 0 <= ep_idx < len(targets):
            idx = targets[ep_idx]

            if idx is not None:
                file_path = name_by_idx.get(idx)
            elif not is_multi_file and file_list:
                file_path = file_list[0].name
            else:
                file_path = None

            vlc_url = _webtorrent_vlc_url(magnet_link, torrent_name, file_path, is_multi_file)

            # No scroll region- webtorrent clears through them.
            # Episode info goes in the terminal title bar instead.
            _print_stream_header(ep_idx, len(targets), idx, multi, vlc_url, use_scroll_region=False)

            cmd = [wt_path, "download", magnet_link, "--vlc", "--no-quit", "--port", "8080"]
            if idx is not None:
                cmd.extend(["--select", str(idx - 1)])

            rc, nav = _run_stream(cmd, vlc_url, allow_navigate=multi, quiet=quiet)

            if nav == "next":
                _kill_vlc()
                time.sleep(1)
                ep_idx += 1
                continue
            elif nav == "back":
                _kill_vlc()
                time.sleep(1)
                ep_idx -= 1
                continue
            else:
                break

        _reset_terminal_title()
        time.sleep(0.5)  # let dying processes flush their final output
        _clear_terminal()
        console.print("\n[success] Streaming session(s) ended![/success]")
    except KeyboardInterrupt:
        _reset_terminal_title()
        time.sleep(0.5)
        _clear_terminal()
        console.print("\n[warning] Streaming cancelled.[/warning]\n")
    except FileNotFoundError:
        _reset_terminal_title()
        console.print("[error] webtorrent-cli not found. Install with: npm install -g webtorrent-cli[/error]\n")


def stream_with_peerflix(
    magnet_link: str,
    select_indexes: list[int] | None = None,
    files=None,  # TorrentMetadata | None
) -> None:
    """Stream selected files to VLC using peerflix.

    One session per selected 1-based index. peerflix serves the currently
    streaming file at the server root, so the 'v' hotkey URL is fixed.

    When no explicit selection is passed, aria2c is available, and the
    torrent looks like a multi-episode release, every video file is queued
    in episode order so `n`/`b` navigation works seamlessly.
    """
    pf_path = shutil.which("peerflix")
    if not pf_path:
        console.print("[error] peerflix not found. Install with: npm install -g peerflix[/error]\n")
        return

    from torrent_meta import fetch_file_list, is_multi_episode, sort_episodes, video_files

    targets: list[int | None] = list(select_indexes) if select_indexes else []

    if targets:
        # Fetch metadata (if available) so we can filter out non-video picks.
        if files is None and has_aria2():
            console.print("[info]Fetching metadata to validate selection...[/info]")
            with console.status("[bold cyan]Fetching metadata...", spinner="dots"):
                files = fetch_file_list(magnet_link)
        file_list = files.files if files is not None else []
        if file_list:
            video_idxs = {f.index for f in video_files(file_list)}
            filtered = [i for i in targets if i in video_idxs]
            skipped = len(targets) - len(filtered)
            if skipped and filtered:
                console.print(
                    f"[warning] Skipping {skipped} non-video file(s) — streamable files only.[/warning]"
                )
            if not filtered:
                console.print(
                    "[error] Selection contains no streamable video files. "
                    "Pick a video file or use a download method instead.[/error]\n"
                )
                return
            targets = filtered
    else:
        # No explicit picker selection — try auto-detect so n/b nav can work.
        if files is None and has_aria2():
            console.print("[info]Fetching metadata to detect episodes...[/info]")
            with console.status("[bold cyan]Fetching metadata...", spinner="dots"):
                files = fetch_file_list(magnet_link)
        file_list = files.files if files is not None else []
        if file_list and is_multi_episode(file_list):
            targets = [f.index for f in sort_episodes(file_list)]
        else:
            targets = [None]

    multi = len(targets) > 1
    vlc_url = "http://127.0.0.1:8888/"
    quiet = is_quiet_mode()

    try:
        ep_idx = 0
        while 0 <= ep_idx < len(targets):
            idx = targets[ep_idx]

            # Quiet mode suppresses subprocess UI — no need for a scroll
            # region since nothing scrolls below the header.
            _print_stream_header(
                ep_idx, len(targets), idx, multi, vlc_url,
                use_scroll_region=not quiet,
            )

            cmd = [pf_path, magnet_link, "--vlc", "--port", "8888"]
            if idx is not None:
                cmd.extend(["-i", str(idx - 1)])

            rc, nav = _run_stream(cmd, vlc_url, allow_navigate=multi, quiet=quiet)

            if nav == "next":
                _kill_vlc()
                time.sleep(1)
                ep_idx += 1
                continue
            elif nav == "back":
                _kill_vlc()
                time.sleep(1)
                ep_idx -= 1
                continue
            else:
                break

        _reset_scroll_region()
        _reset_terminal_title()
        time.sleep(0.5)  # let dying processes flush their final output
        _clear_terminal()
        console.print("\n[success] Streaming session(s) ended![/success]")
    except KeyboardInterrupt:
        _reset_scroll_region()
        _reset_terminal_title()
        time.sleep(0.5)
        _clear_terminal()
        console.print("\n[warning] Streaming cancelled.[/warning]\n")
    except FileNotFoundError:
        _reset_scroll_region()
        _reset_terminal_title()
        console.print("[error] peerflix not found. Install with: npm install -g peerflix[/error]\n")

