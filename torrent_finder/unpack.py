"""Unpacking downloaded page archives: manga and comic chapters or volumes
stored as .zip/.cbz/.rar/.cbr/.7z/.cb7 that hold only images.

With the "Unpack page archives" setting on, a finished in-app download
(Madokami files; aria2c, webtorrent and peerflix torrents) unpacks each such
archive into a folder of the same name beside it, then deletes the archive.
Any other archive (a game's .rar, a zip with programs or documents) is left
alone. ZIP-based archives open with Python's zipfile; RAR and 7z need a program
that reads them: the tar built into Windows 10/11 and macOS (bsdtar), 7-Zip or
UnRAR.

Unpacking happens in a temporary folder beside the archive. The archive is
deleted only after its pages are in place, so a failure keeps it untouched.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

SETTING = "unpack_page_archives"

PAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".jxl", ".tif", ".tiff",
                             ".heic"})
# Small files that come with pages: ComicInfo.xml, credits, Thumbs.db, checksums.
_COMPANION_EXTENSIONS = frozenset({".xml", ".txt", ".nfo", ".url", ".ini", ".json", ".db", ".sfv", ".md5"})
_ARCHIVE_EXTENSIONS = (".zip", ".cbz", ".rar", ".cbr", ".7z", ".cb7")
_COMIC_EXTENSIONS = (".cbz", ".cbr", ".cb7")
# Later volumes of a split RAR can't be read alone; a split archive is never pages.
_SPLIT_RAR = re.compile(r"\.part\d+\.rar$", re.I)
_TOOL_TIMEOUT = 900


@dataclass
class Report:
    unpacked: list = field(default_factory=list)  # folders the pages went to
    kept: list = field(default_factory=list)  # (archive path, why it stayed packed)


def enabled() -> bool:
    from torrent_finder.state import load_setting
    return bool(load_setting(SETTING, False))


def is_archive(path: str) -> bool:
    low = path.casefold()
    return low.endswith(_ARCHIVE_EXTENSIONS) and not _SPLIT_RAR.search(low)


def unpack_all(paths, *, expect_pages: bool = False, status=None) -> Report:
    """Unpack the page archives among *paths*. *expect_pages*: they come from a
    manga library, so an archive that can't be read is reported; elsewhere only
    comic archives (.cbz/.cbr/.cb7) are. ``status(text)`` names each one."""
    report = Report()
    archives = [path for path in paths if is_archive(path)]
    for number, path in enumerate(archives, 1):
        if status:
            status(f"Unpacking ({number}/{len(archives)}) {os.path.basename(path)}")
        folder, problem = unpack(path, expect_pages=expect_pages)
        if folder:
            report.unpacked.append(folder)
        elif problem:
            report.kept.append((path, problem))
    return report


def unpack(path: str, *, expect_pages: bool = False) -> "tuple[str | None, str]":
    """Unpack one page archive into a folder named after it and delete it.

    Returns ``(folder, "")`` on success; ``(None, "")`` when it isn't a page
    archive; ``(None, why)`` when pages could not be unpacked (the archive is
    kept). A single top-level folder inside the archive is not repeated.
    """
    expect_pages = expect_pages or path.casefold().endswith(_COMIC_EXTENSIONS)
    extension = os.path.splitext(path)[1].casefold()
    try:
        if zipfile.is_zipfile(path):
            reader = _ZipReader(path)
        else:
            reader = _tool_reader(path)
            if reader is None:
                if not _tools():
                    return None, (f"no program here opens {extension} files; install 7-Zip or UnRAR"
                                  if expect_pages else "")
                return None, ("couldn't be read (damaged, or a format this computer can't open)"
                              if expect_pages else "")
        if not _is_pages(reader.names):
            return None, ""
        parent = os.path.dirname(os.path.abspath(path))
        scratch = tempfile.mkdtemp(prefix=".unpacking-", dir=parent)
        try:
            reader.extract(scratch)
            root = _content_root(scratch)
            if root is None:
                return None, "its contents weren't only pages after all"
            stem = os.path.splitext(os.path.abspath(path))[0].rstrip(". ")
            folder = _move_to_free_name(root, stem if os.path.basename(stem) else os.path.abspath(path) + " pages")
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    except Exception as error:  # damaged data, an unsupported method, a full disk: keep the archive
        return None, f"couldn't be unpacked ({error})"
    try:
        os.remove(path)
    except OSError:
        pass  # pages are in place; the archive merely stays too
    return folder, ""


def _is_pages(names) -> bool:
    """Every file is a page image or a small companion, with at least one page."""
    files = [name.replace("\\", "/").strip("/") for name in names]
    folders = {name.rsplit("/", 1)[0] for name in files if "/" in name}
    folders |= {"/".join(name.split("/")[:depth]) for name in folders for depth in range(1, name.count("/") + 1)}
    pages = 0
    for name in files:
        parts = name.split("/")
        if not name or name in folders or parts[0] == "__MACOSX" or parts[-1].startswith("."):
            continue
        extension = os.path.splitext(parts[-1])[1].casefold()
        if extension in PAGE_EXTENSIONS:
            pages += 1
        elif extension not in _COMPANION_EXTENSIONS:
            return False
    return pages > 0


def _content_root(scratch: str) -> "str | None":
    """The unpacked folder to keep: *scratch*, or the one folder it holds.
    None when something other than pages came out, or a link."""
    shutil.rmtree(os.path.join(scratch, "__MACOSX"), ignore_errors=True)
    names = []
    for here, folders, files in os.walk(scratch):
        for name in folders + files:
            full = os.path.join(here, name)
            if os.path.islink(full):
                return None
            if name in files:
                names.append(os.path.relpath(full, scratch))
    if not _is_pages(names):
        return None
    entries = os.listdir(scratch)
    if len(entries) == 1 and os.path.isdir(os.path.join(scratch, entries[0])):
        return os.path.join(scratch, entries[0])
    return scratch


def _move_to_free_name(source: str, target: str) -> str:
    """Rename *source* to *target*, or ``target (1)``… when that name is taken."""
    for number in range(1000):
        candidate = f"{target} ({number})" if number else target
        if os.path.lexists(candidate):
            continue
        os.rename(source, candidate)
        return candidate
    raise OSError(f"No free folder name for {target}")


class _ZipReader:
    def __init__(self, path):
        self.path = path
        with zipfile.ZipFile(path) as archive:
            self.names = [info.filename for info in archive.infolist() if not info.is_dir()]

    def extract(self, destination):
        with zipfile.ZipFile(self.path) as archive:
            archive.extractall(destination)  # zipfile drops absolute paths and ".."


def _tools() -> list:
    """Programs that read RAR and 7z here, as (kind, executable), best first."""
    found = []
    if os.name == "nt":
        system = os.environ.get("SystemRoot", r"C:\Windows")
        programs = os.environ.get("ProgramFiles", r"C:\Program Files")
        found += [("bsdtar", os.path.join(system, "System32", "tar.exe")),
                  ("7z", os.path.join(programs, "7-Zip", "7z.exe")),
                  ("unrar", os.path.join(programs, "WinRAR", "UnRAR.exe"))]
    elif sys.platform == "darwin":
        found.append(("bsdtar", "/usr/bin/tar"))
    found += [("bsdtar", shutil.which("bsdtar")), *(("7z", shutil.which(name)) for name in ("7z", "7zz", "7za")),
              ("unrar", shutil.which("unrar"))]
    seen, tools = set(), []
    for kind, executable in found:
        if executable and os.path.isfile(executable) and executable not in seen:
            seen.add(executable)
            tools.append((kind, executable))
    return tools


def _run(command) -> "subprocess.CompletedProcess":
    return subprocess.run(command, capture_output=True, timeout=_TOOL_TIMEOUT, stdin=subprocess.DEVNULL)


class _ToolReader:
    def __init__(self, kind, executable, path, names):
        self.kind, self.executable, self.path, self.names = kind, executable, path, names

    def extract(self, destination):
        command = {
            "bsdtar": [self.executable, "-xf", self.path, "-C", destination],
            "7z": [self.executable, "x", "-y", "-bd", f"-o{destination}", self.path],
            "unrar": [self.executable, "x", "-y", "-idq", self.path, destination + os.sep],
        }[self.kind]
        if _run(command).returncode != 0:
            raise RuntimeError(f"{os.path.basename(self.executable)} failed")


def _tool_reader(path: str) -> "_ToolReader | None":
    """The first program that lists *path*, with the names it listed."""
    rar = path.casefold().endswith((".rar", ".cbr"))
    for kind, executable in _tools():
        if kind == "unrar" and not rar:
            continue
        command = {"bsdtar": [executable, "-tf", path], "7z": [executable, "l", "-ba", "-slt", path],
                   "unrar": [executable, "lb", path]}[kind]
        try:
            listed = _run(command)
        except (OSError, subprocess.SubprocessError):
            continue
        if listed.returncode != 0:
            continue
        lines = listed.stdout.decode("utf-8", errors="replace").splitlines()
        if kind == "7z":
            lines = [line[len("Path = "):] for line in lines if line.startswith("Path = ")]
        names = [line for line in (line.strip() for line in lines) if line]
        if names:
            return _ToolReader(kind, executable, path, names)
    return None


def torrent_files(download_dir: str, metadata=None, indexes=None, magnet: str = "") -> list:
    """The files one finished torrent download wrote that can be found: from
    its file list when known (only *indexes*, 1-based, when given), else
    everything under the magnet's name. Never a path outside *download_dir*."""
    base = os.path.realpath(download_dir)

    def inside(path):
        real = os.path.realpath(path)
        try:
            return real != base and os.path.commonpath([real, base]) == base
        except ValueError:  # another drive
            return False

    if metadata is not None:
        # A single-file torrent is saved under its name; a multi-file one in a folder of that name.
        single = len(metadata.files) == 1 and metadata.files[0].name == metadata.name
        found = []
        for item in metadata.files:
            if indexes and item.index not in indexes:
                continue
            parts = [part for part in item.name.split("/") if part]
            path = os.path.join(download_dir, metadata.name) if single else os.path.join(download_dir, metadata.name, *parts)
            if parts and inside(path) and os.path.isfile(path):
                found.append(path)
        return found
    name = (parse_qs(urlparse(magnet).query).get("dn") or [""])[0]
    if not name or name in (".", "..") or os.path.basename(name) != name or "/" in name or "\\" in name:
        return []
    root = os.path.join(download_dir, name)
    if not inside(root):
        return []
    if os.path.isfile(root):
        return [root]
    return [os.path.join(here, file) for here, _folders, files in os.walk(root) for file in sorted(files)]


def summary_lines(report: Report) -> list:
    """Rich-markup lines saying what was unpacked and what stayed packed."""
    from rich.markup import escape

    lines = []
    if report.unpacked:
        lines.append(f"[success]✓ Unpacked {len(report.unpacked)} archive(s) into folders of pages.[/success]")
    for path, problem in report.kept[:4]:
        lines.append(f"[warning]Kept {escape(os.path.basename(path))} packed:[/warning] {escape(problem)}")
    if len(report.kept) > 4:
        lines.append(f"[dim]… and {len(report.kept) - 4} more kept packed.[/dim]")
    return lines
