"""Download methods: torrent client (magnet) and webtorrent direct download."""

import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from typing import TYPE_CHECKING

from torrent_finder.constants import console, get_download_dir
from torrent_finder.state import load_setting
from torrent_finder.torrent_meta import compact_ranges
from torrent_finder.ui.streaming import (
    _clear_terminal,
    _print_stream_header,
    _reset_scroll_region,
    _reset_terminal_title,
)

if TYPE_CHECKING:
    from torrent_finder.torrent_session import TorrentSession


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


def _wait_for_port(host: str, port: int, timeout: float = 30.0) -> bool:
    """Block until *host:port* accepts a TCP connection, or *timeout* elapses."""
    import socket
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.25)
    return False


def _build_vlc_cmd(url: str, sub_paths: list[str] | None) -> list[str] | None:
    """Construct the VLC argv list. None if VLC isn't installed.

    VLC's first ``--sub-file`` is the primary subtitle track; additional subs
    can be attached as input slaves so the user can toggle between them in
    VLC's Subtitle menu.
    """
    vlc_path = _resolve_vlc_path()
    if not vlc_path:
        return None
    cmd = [vlc_path, url]
    if sub_paths:
        cmd.extend(["--sub-file", sub_paths[0]])
        for extra in sub_paths[1:]:
            cmd.extend(["--input-slave", extra])
    return cmd


def _launch_vlc(url: str, sub_paths: list[str] | None) -> bool:
    """Spawn VLC with the stream URL (+ optional subs). Returns True on launch."""
    cmd = _build_vlc_cmd(url, sub_paths)
    if cmd is not None:
        try:
            subprocess.Popen(cmd)
            return True
        except Exception:
            pass
    # Fallback: hand the URL to the OS — won't carry sub args
    try:
        if platform.system() == "Windows":
            os.startfile(url)  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", url])
        else:
            subprocess.Popen(["xdg-open", url])
        return True
    except Exception:
        return False


def _fetch_torrent_subs(magnet: str, files_meta, indexes: list[int]) -> dict[int, str]:
    """Download a subset of torrent files (subtitles) via aria2c.

    Returns ``{file_index: local_path}`` for files that successfully landed
    on disk. Used to make in-torrent subs available to VLC's ``--sub-file``
    before the stream starts.
    """
    if not has_aria2() or not indexes or files_meta is None:
        return {}

    import tempfile

    tmpdir = tempfile.mkdtemp(prefix="trnt_subs_")
    cmd = [
        "aria2c",
        f"--select-file={compact_ranges(indexes)}",
        "--bt-remove-unselected-file=true",
        "--file-allocation=none",
        "--follow-torrent=false",
        "--seed-time=0",
        "--summary-interval=0",
        "--console-log-level=warn",
        "--bt-stop-timeout=90",
        "-d", tmpdir,
        magnet,
    ]
    try:
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=180,
        )
    except (subprocess.TimeoutExpired, OSError):
        return {}

    idx_to_file = {f.index: f for f in files_meta.files}
    multi_file = len(files_meta.files) > 1
    result: dict[int, str] = {}
    for i in indexes:
        f = idx_to_file.get(i)
        if not f:
            continue
        path = (
            os.path.join(tmpdir, files_meta.name, *f.name.split("/"))
            if multi_file
            else os.path.join(tmpdir, f.name)
        )
        if os.path.exists(path):
            result[i] = path
    return result


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
    subs_holder: list | None = None,
    advance_event: threading.Event | None = None,
    back_event: threading.Event | None = None,
) -> threading.Event:
    """Listen for 'v' (reopen VLC), 'n' (next episode), and 'b' (previous episode).

    url_holder is a single-element list so callers can update the URL after
    capturing it from a subprocess's stdout. subs_holder, when provided, holds
    ``list[str] | None`` of subtitle file paths to attach when relaunching VLC.
    advance_event, when provided, is set on 'n' so the caller can terminate the
    current session and move on. back_event, when provided, is set on 'b' to go
    back to the previous episode.
    """
    stop_event = threading.Event()

    def listener():
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
                        subs = subs_holder[0] if subs_holder else None
                        _launch_vlc(url, subs)
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


def open_torrent_file(path: str) -> bool:
    """Open a ``.torrent`` file with the system default torrent client. Returns
    True on success (used by the Online-Fix flow, which downloads a .torrent and
    hands it off rather than building a magnet)."""
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


def has_peerflix() -> bool:
    """Check if peerflix is installed."""
    return shutil.which("peerflix") is not None


def has_webtorrent() -> bool:
    """Check if webtorrent-cli is installed."""
    return shutil.which("webtorrent") is not None


def has_aria2() -> bool:
    """Check if aria2c is installed."""
    return shutil.which("aria2c") is not None


def _spawn_detached(cmd: list[str], quiet: bool) -> subprocess.Popen:
    """Spawn a download child outside the console's Ctrl+C delivery.

    Ctrl+C must interrupt only *this* process. When the console delivered it to
    the whole group, a fast-dying child (webtorrent) could let the wait return
    before Python raised its own KeyboardInterrupt — the interrupt then fired
    *after* the caller's try/except and unwound the whole program. With the
    child in its own process group (Windows) / session (POSIX), the
    KeyboardInterrupt always lands in our ``proc.wait()`` and the child is
    stopped explicitly (see ``_cancel_download_proc``).
    """
    stdout_arg, stderr_arg = _quiet_streams(quiet)
    kwargs: dict = {"stdout": stdout_arg, "stderr": stderr_arg, "stdin": subprocess.DEVNULL}
    if platform.system() == "Windows":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def _cancel_download_proc(proc: subprocess.Popen) -> None:
    """Stop a detached download child after the user's Ctrl+C: ask nicely first
    (CTRL_BREAK on Windows — aria2c treats it like Ctrl+C and saves its control
    file so the download stays resumable), then hard-kill the tree."""
    if platform.system() == "Windows":
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
            proc.wait(timeout=5)
            return
        except Exception:
            pass
    _kill_process_tree(proc)


def _run_download(cmd: list[str], quiet: bool, status_msg: str) -> int | None:
    """Run one download subprocess to completion. Returns its exit code, or
    None when the user cancelled with Ctrl+C. In quiet mode the child's native
    UI is suppressed and a spinner renders instead."""
    proc = _spawn_detached(cmd, quiet)
    try:
        if quiet:
            with console.status(status_msg, spinner="dots"):
                return proc.wait()
        return proc.wait()
    except KeyboardInterrupt:
        _cancel_download_proc(proc)
        return None


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

    dl_dir = get_download_dir()
    os.makedirs(dl_dir, exist_ok=True)
    console.print(f"[info]Downloading to:[/info] [highlight]{dl_dir}[/highlight]")
    if select_indexes:
        console.print(f"[info]Selected files:[/info] [highlight]{compact_ranges(select_indexes)}[/highlight] ({len(select_indexes)} file(s))")
    console.print("[bold red]To cancel, press CTRL+C at any time.[/bold red]\n")

    cmd = [
        aria_path,
        "-d", dl_dir,
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
        rc = _run_download(cmd, quiet, "[bold cyan]Downloading…[/bold cyan]  Ctrl+C cancel")
        if rc is None:
            console.print("\n[warning] Download cancelled.[/warning]\n")
            return False
        console.print()
        if rc == 0:
            console.print("[success] Download complete![/success]")
            console.print(f"[info]Files saved to:[/info] [highlight]{dl_dir}[/highlight]\n")
            return True
        console.print(f"[error] Download failed (exit code {rc}).[/error]\n")
        return False
    except KeyboardInterrupt:
        console.print("\n[warning] Download cancelled.[/warning]\n")
        return False
    except FileNotFoundError:
        console.print("[error] aria2c not found. Install from https://aria2.github.io/[/error]\n")
        return False


def download_many_with_aria2(magnets: list[str]) -> bool:
    """Download several torrents with a single aria2c process (parallel).

    The client-free batch path: aria2c accepts every magnet at once and pulls
    them concurrently. Batch download grabs whole torrents (no per-file
    selection). Returns True on a clean exit, False on cancel/failure.
    """
    aria_path = shutil.which("aria2c")
    if not aria_path:
        console.print("[error] aria2c not found. Install from https://aria2.github.io/[/error]\n")
        return False
    if not magnets:
        return False

    dl_dir = get_download_dir()
    os.makedirs(dl_dir, exist_ok=True)
    console.print(f"[info]Downloading to:[/info] [highlight]{dl_dir}[/highlight]")
    console.print(f"[info]Torrents:[/info] [highlight]{len(magnets)}[/highlight] (downloaded in parallel)")
    console.print("[bold red]To cancel, press CTRL+C at any time.[/bold red]\n")

    cmd = [
        aria_path,
        "-d", dl_dir,
        "--seed-time=0",
        "--console-log-level=warn",
    ] + list(magnets)

    quiet = is_quiet_mode()
    try:
        rc = _run_download(
            cmd, quiet,
            f"[bold cyan]Downloading {len(magnets)} torrent(s)…[/bold cyan]  Ctrl+C cancel",
        )
        if rc is None:
            console.print("\n[warning] Downloads cancelled.[/warning]\n")
            return False
        console.print()
        if rc == 0:
            console.print("[success] Downloads complete![/success]")
            console.print(f"[info]Files saved to:[/info] [highlight]{dl_dir}[/highlight]\n")
            return True
        console.print(f"[error] Some downloads failed (exit code {rc}).[/error]\n")
        return False
    except KeyboardInterrupt:
        console.print("\n[warning] Downloads cancelled.[/warning]\n")
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

    dl_dir = get_download_dir()
    os.makedirs(dl_dir, exist_ok=True)
    console.print(f"[info]Downloading to:[/info] [highlight]{dl_dir}[/highlight]")
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
            cmd = [wt_path, "download", magnet_link, "--out", dl_dir]
            if idx is not None:
                cmd.extend(["--select", str(idx - 1)])  # webtorrent is 0-based
            rc = _run_download(
                cmd, quiet,
                f"[bold cyan]Downloading…[/bold cyan]  "
                f"{'session ' + str(n) + '/' + str(len(targets)) + '  •  ' if len(targets) > 1 else ''}"
                "Ctrl+C cancel",
            )
            if rc is None:
                console.print("\n[warning] Download cancelled.[/warning]\n")
                return False
            if rc != 0:
                console.print(f"\n[error] Session {n} failed (exit code {rc}).[/error]\n")
                return False

        console.print()
        console.print("[success] Download complete![/success]")
        console.print(f"[info]Files saved to:[/info] [highlight]{dl_dir}[/highlight]\n")
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

    dl_dir = get_download_dir()
    os.makedirs(dl_dir, exist_ok=True)
    console.print(f"[info]Downloading to:[/info] [highlight]{dl_dir}[/highlight]")
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
            cmd = [pf_path, magnet_link, "--path", dl_dir]
            if idx is not None:
                cmd.extend(["-i", str(idx - 1)])  # peerflix is 0-based
            rc = _run_download(
                cmd, quiet,
                f"[bold cyan]Downloading…[/bold cyan]  "
                f"{'session ' + str(n) + '/' + str(len(targets)) + '  •  ' if len(targets) > 1 else ''}"
                "Ctrl+C cancel",
            )
            if rc is None:
                console.print("\n[warning] Download cancelled.[/warning]\n")
                return False
            if rc != 0:
                console.print(f"\n[error] Session {n} failed (exit code {rc}).[/error]\n")
                return False

        console.print()
        console.print("[success] Download complete![/success]")
        console.print(f"[info]Files saved to:[/info] [highlight]{dl_dir}[/highlight]\n")
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
    sub_paths: list[str] | None = None,
    launch_vlc_when_ready: tuple[str, int] | None = None,
) -> tuple[int, str]:
    """Run a streaming subprocess with native TTY (no stdout piping).

    vlc_url, if provided, is what the 'v' hotkey will relaunch VLC with.
    sub_paths, if provided, is the list of subtitle file paths attached to
    each VLC relaunch (primary = first entry; rest become input slaves).
    launch_vlc_when_ready, when set to ``(host, port)``, makes ``_run_stream``
    poll that TCP socket and spawn VLC ourselves with ``vlc_url`` + ``sub_paths``
    as soon as the streaming server is up — replaces webtorrent/peerflix's own
    ``--vlc`` flag so we control VLC's argv (and can attach ``--sub-file``).
    When allow_navigate is True, 'n'/'b' terminate the subprocess so the
    caller can advance or go back in a multi-ep flow. Returns (returncode,
    nav_action) where nav_action is 'next', 'back', or 'none'.

    When quiet is True, subprocess stdout/stderr are redirected to DEVNULL
    (full-screen UI suppressed) and a rich spinner renders in its place.
    """
    url_holder: list[str | None] = [vlc_url]
    subs_holder: list[list[str] | None] = [sub_paths]
    advance_event = threading.Event() if allow_navigate else None
    back_event = threading.Event() if allow_navigate else None
    stop_event = _start_vlc_hotkey_thread(url_holder, subs_holder, advance_event, back_event)

    stdout_arg, stderr_arg = _quiet_streams(quiet)
    # stdin=DEVNULL so the child can't steal our v/n/b keystrokes — the hotkey
    # thread owns stdin. Side-effect: webtorrent/peerflix's own SPACE/CTRL+L
    # keybinds stop working, but those aren't surfaced in our header anyway.
    # cwd=system tempdir keeps webtorrent's transient files out of the user's
    # working directory.
    # New process group / session for the same reason as _spawn_detached: the
    # console must deliver Ctrl+C to us alone, so the KeyboardInterrupt always
    # lands inside this function's try (which kills the child tree) instead of
    # racing the child's own death and escaping the caller's except scope.
    import tempfile as _tempfile
    detach: dict = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if platform.system() == "Windows"
        else {"start_new_session": True}
    )
    proc = subprocess.Popen(
        cmd,
        stdout=stdout_arg,
        stderr=stderr_arg,
        stdin=subprocess.DEVNULL,
        cwd=_tempfile.gettempdir(),
        **detach,
    )
    nav_action = "none"

    if launch_vlc_when_ready and vlc_url:
        host, port = launch_vlc_when_ready

        def vlc_waiter():
            if _wait_for_port(host, port, timeout=60):
                # Grace period for the server to register the selected file's
                # route. webtorrent-cli accepts connections on the port well
                # before /webtorrent/<infohash>/<encoded_path> resolves to a
                # real BitTorrent piece, so VLC's first GET can 404 if we
                # launch too eagerly. 2s smooths most multi-file torrents.
                time.sleep(2.0)
                if not _vlc_running():
                    _launch_vlc(vlc_url, sub_paths)

        threading.Thread(target=vlc_waiter, daemon=True).start()

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


def _resolve_subs_for_session(
    magnet_link: str,
    files_meta,
    file_list: list,
    sub_choice: dict | None,
) -> dict[int, list[str]]:
    """Return ``{video_file_index: [local_sub_paths]}`` for the current session.

    Modes (via ``sub_choice``):
      * ``"off"`` — no subs.
      * ``"external"`` — pin the chosen subtitle(s) to every video index.
        Accepts ``sub_choice["paths"]`` (ordered list; first = primary track)
        or the legacy single ``sub_choice["path"]``.
      * ``"auto"`` (default) — scan ``file_list`` for sub files paired with each
        video (by basename / language tag / sibling-folder + ep number),
        batch-fetch them with aria2c, and map by video index.

    Empty dict means "no subtitles to attach"; callers should pass ``None``
    as the ``sub_paths`` arg to ``_run_stream`` in that case.
    """
    from torrent_finder.torrent_meta import match_subtitles_for, video_files as _vids

    mode = (sub_choice or {}).get("mode", "auto")

    if mode == "off":
        return {}

    if mode == "external":
        raw_paths = (sub_choice or {}).get("paths")
        if not raw_paths:
            single = (sub_choice or {}).get("path")
            raw_paths = [single] if single else []
        # Keep order (primary first); VLC takes the first as --sub-file and the
        # rest as input-slaves, so the user can switch tracks in VLC.
        abs_paths = [os.path.abspath(p) for p in raw_paths if p and os.path.exists(p)]
        if not abs_paths:
            console.print(
                "[warning] External subtitle path missing or not found — streaming without subs.[/warning]"
            )
            return {}
        if file_list:
            return {f.index: list(abs_paths) for f in _vids(file_list)}
        return {-1: list(abs_paths)}  # single-file / no metadata: use sentinel index

    # auto-detect from torrent
    if not file_list:
        return {}
    per_video: dict[int, list[int]] = {}
    needed: set[int] = set()
    for f in _vids(file_list):
        matches = match_subtitles_for(f.name, file_list)
        if matches:
            ids = [m.index for m in matches]
            per_video[f.index] = ids
            needed.update(ids)
    if not needed:
        return {}

    console.print(
        f"[info]Found {len(needed)} subtitle file(s) inside torrent — fetching via aria2c…[/info]"
    )
    with console.status("[bold cyan]Downloading subtitles…[/bold cyan]", spinner="dots"):
        local = _fetch_torrent_subs(magnet_link, files_meta, sorted(needed))

    if not local:
        console.print(
            "[warning] Could not fetch in-torrent subtitles — streaming without subs.[/warning]"
        )
        return {}

    result: dict[int, list[str]] = {}
    for vid_idx, sub_ids in per_video.items():
        paths = [local[i] for i in sub_ids if i in local]
        if paths:
            result[vid_idx] = paths
    return result


def stream_with_webtorrent(session: "TorrentSession") -> None:
    """Stream selected files from *session* to VLC using webtorrent-cli.

    Reads precedence + metadata + sub paths off the session; renders the
    per-episode subprocess loop here. webtorrent-cli uses full-screen ANSI
    rendering (``\033[2J``) that clears through scroll regions, so we use
    the terminal window title for persistent episode info instead.
    """
    wt_path = shutil.which("webtorrent")
    if not wt_path:
        console.print("[error] webtorrent-cli not found. Install with: npm install -g webtorrent-cli[/error]\n")
        return

    magnet_link = session.magnet

    if session.selected_files:
        # User-supplied selection may include non-video files (artwork, .nfo,
        # subs). Session.stream_indexes already filters them out; warn about
        # the skipped count, and bail if everything was non-video.
        n_skipped = len(session.selected_files) - len(session.stream_indexes)
        if n_skipped and session.stream_indexes:
            console.print(
                f"[warning] Skipping {n_skipped} non-video file(s) — streamable files only.[/warning]"
            )
        if not session.stream_indexes and session.file_list:
            console.print(
                "[error] Selection contains no streamable video files. "
                "Pick a video file or use a download method instead.[/error]\n"
            )
            return

    file_list = session.file_list
    targets: list[int | None] = list(session.stream_indexes) if session.stream_indexes else [None]

    multi = len(targets) > 1
    name_by_idx = {f.index: f.name for f in file_list}
    is_multi_file = len(file_list) > 1
    torrent_name = session.torrent_name
    quiet = is_quiet_mode()

    sub_map = session.sub_paths

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

            # Subs for this episode: prefer per-video map entry, fall back to
            # sentinel index (-1) used by external-mode single-file torrents.
            if idx is not None and idx in sub_map:
                ep_subs = sub_map[idx]
            elif -1 in sub_map:
                ep_subs = sub_map[-1]
            else:
                ep_subs = None

            # No scroll region- webtorrent clears through them.
            # Episode info goes in the terminal title bar instead.
            _file_info = next((f for f in file_list if f.index == idx), None) if idx is not None else None
            _print_stream_header(
                ep_idx, len(targets), idx, multi, vlc_url,
                use_scroll_region=False, sub_paths=ep_subs,
                backend="webtorrent",
                filename=_file_info.name if _file_info else "",
                filesize_bytes=_file_info.size_bytes if _file_info else 0,
            )

            cmd = [wt_path, "download", magnet_link, "--port", "8080"]
            if idx is not None:
                cmd.extend(["--select", str(idx - 1)])

            rc, nav = _run_stream(
                cmd, vlc_url, allow_navigate=multi, quiet=quiet,
                sub_paths=ep_subs,
                launch_vlc_when_ready=("127.0.0.1", 8080),
            )

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


def stream_with_peerflix(session: "TorrentSession") -> None:
    """Stream selected files from *session* to VLC using peerflix.

    One subprocess per selected 1-based index; peerflix serves the currently
    streaming file at the server root, so the VLC URL is fixed. Reads
    precedence + metadata + sub paths off the session.
    """
    pf_path = shutil.which("peerflix")
    if not pf_path:
        console.print("[error] peerflix not found. Install with: npm install -g peerflix[/error]\n")
        return

    magnet_link = session.magnet

    if session.selected_files:
        n_skipped = len(session.selected_files) - len(session.stream_indexes)
        if n_skipped and session.stream_indexes:
            console.print(
                f"[warning] Skipping {n_skipped} non-video file(s) — streamable files only.[/warning]"
            )
        if not session.stream_indexes and session.file_list:
            console.print(
                "[error] Selection contains no streamable video files. "
                "Pick a video file or use a download method instead.[/error]\n"
            )
            return

    file_list = session.file_list
    targets: list[int | None] = list(session.stream_indexes) if session.stream_indexes else [None]

    multi = len(targets) > 1
    vlc_url = "http://127.0.0.1:8888/"
    quiet = is_quiet_mode()

    sub_map = session.sub_paths

    try:
        ep_idx = 0
        while 0 <= ep_idx < len(targets):
            idx = targets[ep_idx]

            if idx is not None and idx in sub_map:
                ep_subs = sub_map[idx]
            elif -1 in sub_map:
                ep_subs = sub_map[-1]
            else:
                ep_subs = None

            # Quiet mode suppresses subprocess UI — no need for a scroll
            # region since nothing scrolls below the header.
            _file_info = next((f for f in file_list if f.index == idx), None) if idx is not None else None
            _print_stream_header(
                ep_idx, len(targets), idx, multi, vlc_url,
                use_scroll_region=not quiet, sub_paths=ep_subs,
                backend="peerflix",
                filename=_file_info.name if _file_info else "",
                filesize_bytes=_file_info.size_bytes if _file_info else 0,
            )

            cmd = [pf_path, magnet_link, "--port", "8888"]
            if idx is not None:
                cmd.extend(["-i", str(idx - 1)])

            rc, nav = _run_stream(
                cmd, vlc_url, allow_navigate=multi, quiet=quiet,
                sub_paths=ep_subs,
                launch_vlc_when_ready=("127.0.0.1", 8888),
            )

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

