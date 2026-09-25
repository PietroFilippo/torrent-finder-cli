"""Run a Windows package update after the app releases its launcher.

Invoked only by updates.py. Output goes to a user-local log and the next app
launch reports the actual exit status, including partial upgrade failures.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import time


def _wait_for_parent(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
    if not handle:
        return ctypes.get_last_error() == 87  # Parent has already exited.
    try:
        return kernel.WaitForSingleObject(handle, 900_000) == 0
    finally:
        kernel.CloseHandle(handle)


def write_status(path: Path, **data) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    os.replace(temporary, path)


def run_job(parent_pid: int, command: list[str], status: Path, log: Path) -> None:
    try:
        queued = json.loads(status.read_text(encoding="utf-8"))
        metadata = {}
        if isinstance(queued, dict):
            metadata = {key: queued[key] for key in ("job_id", "started_at", "current", "latest") if key in queued}
    except (OSError, ValueError):
        metadata = {}
    try:
        if not _wait_for_parent(parent_pid):
            raise RuntimeError("The app did not exit within 15 minutes; no update was attempted.")
        # Console-script launcher wrappers exit just after their Python child.
        time.sleep(1)
        write_status(status, state="pending", phase="installing", log=str(log), **metadata)
        with log.open("w", encoding="utf-8") as output:
            result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, timeout=900)
        write_status(status, state="succeeded" if result.returncode == 0 else "failed",
                     log=str(log), returncode=result.returncode, **metadata)
    except Exception as error:
        write_status(status, state="failed", log=str(log), error=str(error), **metadata)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent", type=int, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    run_job(args.parent, command, args.status, args.log)


if __name__ == "__main__":
    main()
