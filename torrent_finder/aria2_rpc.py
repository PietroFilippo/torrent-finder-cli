"""Session-owned, hidden aria2 process and loopback JSON-RPC transport.

No terminal output, environment proxies, or aria2 user configuration. The job
manager owns the single poller; this transport serializes Session requests.
"""

# i18n: converted
import os
import platform
import secrets
import socket
import subprocess
import threading
import time

import requests

from torrent_finder.constants import machine_state_dir
from torrent_finder.downloader import _kill_process_tree, _log_tail
from torrent_finder.i18n import t
from torrent_finder.torrent_meta import compact_ranges


class Aria2Error(RuntimeError):
    """A start or RPC failure, suitable for display by the caller."""


class Aria2Engine:
    def __init__(self, *, state_dir: str | None = None, executable: str = "aria2c"):
        self.state_dir = os.path.abspath(state_dir if state_dir is not None else machine_state_dir())
        self.log_path = os.path.join(self.state_dir, "aria2-background.log")
        self.executable = executable
        self.session = requests.Session()
        self.session.trust_env = False
        self.secret = secrets.token_urlsafe(24)
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self._rpc_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._closed = False

    def start(self) -> None:
        """Start lazily; retry fresh ephemeral ports if a bind race occurs."""
        with self._lifecycle_lock:
            if self._closed:
                raise Aria2Error(t("The background download engine is closed."))
            if self.is_alive():
                return
            os.makedirs(self.state_dir, exist_ok=True)
            for attempt in range(3):
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    probe.bind(("127.0.0.1", 0))
                    self.port = probe.getsockname()[1]
                command = [
                    self.executable, "--no-conf=true", "--enable-rpc",
                    "--rpc-listen-all=false", f"--rpc-listen-port={self.port}",
                    f"--rpc-secret={self.secret}", f"--stop-with-process={os.getpid()}",
                    "--quiet=true", f"--log={self.log_path}", "--log-level=warn",
                    "--max-concurrent-downloads=2", "--seed-time=0",
                    "--bt-remove-unselected-file=true", "--file-allocation=none",
                    "--auto-save-interval=30",
                    f"--dht-file-path={os.path.join(self.state_dir, 'aria2-background-dht.dat')}",
                    f"--dht-file-path6={os.path.join(self.state_dir, 'aria2-background-dht6.dat')}",
                ]
                kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, cwd=self.state_dir)
                if platform.system() == "Windows":
                    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                else:
                    kwargs["start_new_session"] = True
                try:
                    self.proc = subprocess.Popen(command, **kwargs)
                except OSError as error:
                    raise Aria2Error(t("Could not start aria2c: {error}", error=error)) from error
                deadline = time.monotonic() + 5
                while self.is_alive() and time.monotonic() < deadline:
                    try:
                        self.call("aria2.getVersion")
                        return
                    except (Aria2Error, requests.RequestException):
                        time.sleep(0.05)
                if self.is_alive():
                    _kill_process_tree(self.proc)
                self.proc.wait(timeout=5)
                if attempt == 2:
                    raise Aria2Error(t("aria2c could not open its background RPC server: {detail}",
                                       detail=self.log_tail()))

    def call(self, method: str, *params):
        """Authenticated JSON-RPC; multicall authenticates each nested call."""
        values = list(params) if method == "system.multicall" else [f"token:{self.secret}", *params]
        with self._rpc_lock:
            try:
                response = self.session.post(
                    f"http://127.0.0.1:{self.port}/jsonrpc",
                    json={"jsonrpc": "2.0", "id": "torrent-finder", "method": method, "params": values},
                    timeout=3, allow_redirects=False,
                )
                response.raise_for_status()
            except requests.RequestException as error:
                raise Aria2Error(t("Could not contact aria2c: {error}", error=error)) from error
            if 300 <= response.status_code < 400:
                raise Aria2Error(t("aria2c redirected a loopback RPC request."))
            try:
                payload = response.json()
            except ValueError as error:
                raise Aria2Error(t("aria2c returned an invalid RPC response.")) from error
        if not isinstance(payload, dict) or ("result" not in payload and "error" not in payload):
            raise Aria2Error(t("aria2c returned an invalid RPC response."))
        if "error" in payload:
            raise Aria2Error(t("aria2c RPC failed: {error}", error=payload["error"].get("message", payload["error"])))
        return payload["result"]

    def add_uri(self, uri: str, target_dir: str, select: tuple[int, ...] | None = None) -> str:
        self.start()
        options = {"dir": target_dir}
        if select:
            options["select-file"] = compact_ranges(list(select))
        return self.call("aria2.addUri", [uri], options)

    def statuses(self, gids: tuple[str, ...]) -> tuple[dict, ...]:
        calls = [{"methodName": "aria2.tellStatus", "params": [f"token:{self.secret}", gid]}
                 for gid in gids]
        results = self.call("system.multicall", calls)
        if not isinstance(results, list) or len(results) != len(gids):
            raise Aria2Error(t("aria2c returned an invalid RPC response."))
        statuses = []
        for result in results:
            if isinstance(result, dict):
                statuses.append({"status": "error", "errorMessage": result.get("faultString", str(result))})
            elif isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict):
                statuses.append(result[0])
            else:
                raise Aria2Error(t("aria2c returned an invalid RPC response."))
        for status in statuses:
            if status.get("status") not in {"active", "waiting", "paused", "error", "complete", "removed"}:
                raise Aria2Error(t("aria2c returned an invalid RPC response."))
            try:
                for key in ("completedLength", "totalLength", "downloadSpeed", "connections", "numSeeders"):
                    if int(status.get(key, 0)) < 0:
                        raise ValueError(key)
            except (ValueError, TypeError) as error:
                raise Aria2Error(t("aria2c returned an invalid RPC response.")) from error
        return tuple(statuses)

    def remove(self, gid: str) -> None:
        self.call("aria2.remove", gid)

    def remove_result(self, gid: str) -> None:
        self.call("aria2.removeDownloadResult", gid)

    def is_alive(self) -> bool:
        # Popen owns the process handle: os.kill(pid, 0) kills on Windows.
        return self.proc is not None and self.proc.poll() is None

    def log_tail(self) -> str:
        return _log_tail(self.log_path)

    def shutdown(self, graceful: bool = True) -> None:
        """Ask, force, kill, and reap. Safe after failed startup or twice."""
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            try:
                if self.is_alive():
                    methods = [("aria2.shutdown", 5), ("aria2.forceShutdown", 3)]
                    if not graceful:
                        methods = methods[1:]
                    for method, timeout in methods:
                        try:
                            self.call(method)
                            self.proc.wait(timeout=timeout)
                        except (Exception, KeyboardInterrupt):
                            pass
                        if not self.is_alive():
                            break
                    while True:
                        try:
                            if self.is_alive():
                                _kill_process_tree(self.proc)
                            self.proc.wait(timeout=5)
                            break
                        except KeyboardInterrupt:
                            continue  # a second Ctrl+C must still reap the child
            finally:
                self.session.close()
