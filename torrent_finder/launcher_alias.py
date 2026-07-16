"""Managed quick-launch commands for starting torrent-finder from a shell.

The package-owned ``torrent-finder`` command remains canonical. This module
creates at most one optional forwarding shim from a fixed preset list and
records its path in application state. Ownership markers ensure cleanup never
deletes an unrelated command.
"""

from dataclasses import dataclass
import ctypes
import os
import shlex
import shutil
import subprocess
import sys
import sysconfig

from torrent_finder import store
from torrent_finder.state import load_setting, save_setting
from torrent_finder.updates import install_kind


DEFAULT_COMMAND = "torrent-finder"
COMMAND_CHOICES = (DEFAULT_COMMAND, "tf", "torrent", "find-torrent", "tfind")
SETTING_KEY = "terminal_command"
MANAGED_MARKER = "Managed by torrent-finder-cli"

_SOURCE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class LauncherError(RuntimeError):
    """A quick-launch command could not be installed or removed."""


class LauncherConflict(LauncherError):
    """The requested command is already owned by another program."""


@dataclass(frozen=True)
class LaunchTarget:
    argv: tuple[str, ...]
    cwd: str | None = None


@dataclass(frozen=True)
class LauncherStatus:
    name: str
    path: str = ""
    managed: bool = False
    available: bool = False
    path_ready: bool = False


def _normal_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(path)))


def _directory_on_path(directory: str) -> bool:
    wanted = _normal_path(directory)
    return any(
        entry and _normal_path(entry.strip('"')) == wanted
        for entry in os.environ.get("PATH", "").split(os.pathsep)
    )


def _directory_writable(directory: str) -> bool:
    if os.path.isdir(directory):
        return os.access(directory, os.W_OK)
    parent = os.path.dirname(directory) or os.curdir
    return os.path.isdir(parent) and os.access(parent, os.W_OK)


def _find_command(name: str) -> str | None:
    return shutil.which(name)


def launcher_dir() -> str:
    """Choose a user-writable launcher directory, preferring one on PATH."""
    canonical = _find_command(DEFAULT_COMMAND)
    if canonical:
        canonical_dir = os.path.dirname(os.path.abspath(canonical))
        if _directory_writable(canonical_dir):
            return canonical_dir

    user_bin = os.path.expanduser("~/.local/bin")
    if _directory_on_path(user_bin):
        return user_bin

    scripts = sysconfig.get_path("scripts")
    if scripts and _directory_on_path(scripts) and _directory_writable(scripts):
        return scripts
    return user_bin


def resolve_target(kind: str | None = None) -> LaunchTarget:
    """Return the durable command a generated shim should forward to."""
    kind = kind or install_kind()
    if kind == "binary":
        return LaunchTarget((os.path.abspath(sys.executable),))

    canonical = _find_command(DEFAULT_COMMAND)
    if kind == "pip" and canonical:
        return LaunchTarget((os.path.abspath(canonical),))
    if kind == "git":
        return LaunchTarget(
            (os.path.abspath(sys.executable), "-m", "torrent_finder"),
            cwd=_SOURCE_ROOT,
        )
    return LaunchTarget((os.path.abspath(sys.executable), "-m", "torrent_finder"))


def _cmd_quote(value: str) -> str:
    return f'"{value.replace("%", "%%").replace(chr(34), chr(34) * 2)}"'


def _render_launcher(target: LaunchTarget, platform: str | None = None) -> str:
    platform = platform or sys.platform
    if platform == "win32":
        command = " ".join(
            [_cmd_quote(target.argv[0]), subprocess.list2cmdline(target.argv[1:])]
        ).rstrip()
        lines = ["@echo off", f"rem {MANAGED_MARKER}"]
        if target.cwd:
            lines.extend([
                f"pushd {_cmd_quote(target.cwd)}",
                f"{command} %*",
                'set "_TF_EXIT=%ERRORLEVEL%"',
                "popd",
                "exit /b %_TF_EXIT%",
            ])
        else:
            lines.extend([f"{command} %*", "exit /b %ERRORLEVEL%"])
        return "\r\n".join(lines) + "\r\n"

    command = " ".join(shlex.quote(part) for part in target.argv)
    lines = ["#!/bin/sh", f"# {MANAGED_MARKER}"]
    if target.cwd:
        lines.append(f"cd {shlex.quote(target.cwd)} || exit 1")
    lines.append(f'exec {command} "$@"')
    return "\n".join(lines) + "\n"


def _shim_path(name: str, directory: str, platform: str | None = None) -> str:
    platform = platform or sys.platform
    suffix = ".cmd" if platform == "win32" else ""
    return os.path.join(directory, name + suffix)


def _is_managed(path: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            return MANAGED_MARKER in handle.read(1024)
    except OSError:
        return False


def _same_path(first: str, second: str) -> bool:
    return _normal_path(first) == _normal_path(second)


def _is_repo_launcher(name: str, path: str) -> bool:
    return name == "torrent" and _same_path(path, os.path.join(_SOURCE_ROOT, "torrent.bat"))


def _is_packaged_torrent_alias(name: str, path: str) -> bool:
    if name != "torrent":
        return False
    canonical = _find_command(DEFAULT_COMMAND)
    return bool(
        canonical
        and _same_path(os.path.dirname(path), os.path.dirname(canonical))
    )


def _remove_previous(setting, keep_path: str = "") -> None:
    if not isinstance(setting, dict) or not setting.get("managed"):
        return
    old_path = setting.get("path", "")
    if not isinstance(old_path, str) or not old_path:
        return
    if keep_path and _same_path(old_path, keep_path):
        return
    if _is_managed(old_path):
        try:
            os.remove(old_path)
        except OSError:
            pass


def _save_status(name: str, path: str, managed: bool) -> None:
    save_setting(
        SETTING_KEY,
        {"name": name, "path": path, "managed": managed},
    )
    store.flush()


def set_terminal_command(
    name: str,
    *,
    directory: str | None = None,
    target: LaunchTarget | None = None,
    platform: str | None = None,
) -> LauncherStatus:
    """Select a preset command, installing a managed shim when necessary."""
    if name not in COMMAND_CHOICES:
        raise ValueError(f"Unsupported terminal command: {name}")
    if name == DEFAULT_COMMAND:
        return reset_terminal_command()

    platform = platform or sys.platform
    previous = load_setting(SETTING_KEY, None)
    existing = _find_command(name)
    if existing and _is_packaged_torrent_alias(name, existing):
        _remove_previous(previous)
        path = os.path.abspath(existing)
        _save_status(name, path, False)
        return LauncherStatus(name, path, False, True, True)
    if existing and not (_is_managed(existing) or _is_repo_launcher(name, existing)):
        raise LauncherConflict(
            f"'{name}' already resolves to another program: {os.path.abspath(existing)}"
        )

    directory = directory or launcher_dir()
    path = _shim_path(name, directory, platform)
    if os.path.exists(path) and not _is_managed(path):
        raise LauncherConflict(f"Refusing to overwrite existing file: {path}")

    target = target or resolve_target()
    try:
        os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(_render_launcher(target, platform))
        if platform != "win32":
            os.chmod(path, os.stat(path).st_mode | 0o755)
    except OSError as exc:
        raise LauncherError(f"Could not create launcher at {path}: {exc}") from exc

    _remove_previous(previous, keep_path=path)
    path = os.path.abspath(path)
    _save_status(name, path, True)
    ready = _directory_on_path(directory)
    return LauncherStatus(name, path, True, ready, ready)


def reset_terminal_command() -> LauncherStatus:
    """Remove the current managed alias and restore the canonical command."""
    previous = load_setting(SETTING_KEY, None)
    _remove_previous(previous)
    save_setting(SETTING_KEY, None)
    store.flush()
    canonical = _find_command(DEFAULT_COMMAND) or ""
    return LauncherStatus(
        DEFAULT_COMMAND,
        os.path.abspath(canonical) if canonical else "",
        False,
        bool(canonical),
        bool(canonical),
    )


def current_status() -> LauncherStatus:
    """Describe the selected command without mutating state or the filesystem."""
    saved = load_setting(SETTING_KEY, None)
    if isinstance(saved, dict) and saved.get("name") in COMMAND_CHOICES[1:]:
        name = saved["name"]
        path = saved.get("path", "")
        managed = bool(saved.get("managed"))
        exists = bool(
            isinstance(path, str)
            and path
            and os.path.isfile(path)
            and (not managed or _is_managed(path))
        )
        directory = os.path.dirname(path) if isinstance(path, str) else ""
        ready = exists and bool(directory) and _directory_on_path(directory)
        return LauncherStatus(name, path if isinstance(path, str) else "", managed, ready, ready)

    canonical = _find_command(DEFAULT_COMMAND) or ""
    return LauncherStatus(
        DEFAULT_COMMAND,
        os.path.abspath(canonical) if canonical else "",
        False,
        bool(canonical),
        bool(canonical),
    )


def ensure_launcher_dir_on_path(directory: str) -> bool:
    """Add *directory* to the Windows user PATH; return whether it is ready."""
    if _directory_on_path(directory):
        return True
    if sys.platform != "win32":
        return False

    try:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            try:
                current, value_type = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                current, value_type = "", winreg.REG_EXPAND_SZ
            entries = [entry for entry in current.split(os.pathsep) if entry]
            if not any(_normal_path(entry.strip('"')) == _normal_path(directory) for entry in entries):
                entries.append(directory)
                winreg.SetValueEx(key, "Path", 0, value_type, os.pathsep.join(entries))

        os.environ["PATH"] = os.pathsep.join(
            [entry for entry in (os.environ.get("PATH", ""), directory) if entry]
        )
        try:
            ctypes.windll.user32.SendMessageTimeoutW(
                0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, None
            )
        except Exception:
            pass
        return _directory_on_path(directory)
    except (OSError, PermissionError):
        return False
