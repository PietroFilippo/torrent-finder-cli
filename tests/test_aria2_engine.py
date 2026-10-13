"""RPC protocol, hidden process lifecycle, and a real local HTTP transfer."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import requests

import isolation  # noqa: F401
from torrent_finder import aria2_rpc, unpack
from torrent_finder.aria2_rpc import Aria2Engine, Aria2Error


class Aria2EngineTests(unittest.TestCase):
    def setUp(self):
        # Windows platform.system() may itself launch `ver`. Keep that OS
        # probe outside tests that replace subprocess.Popen with a fake child.
        system = patch.object(aria2_rpc.platform, "system", return_value=aria2_rpc.platform.system())
        system.start()
        self.addCleanup(system.stop)
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.engine = Aria2Engine(state_dir=self.root.name)
        self.addCleanup(self.engine.session.close)

    def test_session_ignores_environment_proxies(self):
        self.assertFalse(self.engine.session.trust_env)

    def test_popen_options_on_windows_and_posix(self):
        for system in ("Windows", "Linux", "Darwin"):
            with self.subTest(system=system):
                engine = Aria2Engine(state_dir=self.root.name)
                self.addCleanup(engine.session.close)
                proc = Mock()
                proc.poll.return_value = None
                with patch.object(aria2_rpc.platform, "system", return_value=system), \
                        patch.object(aria2_rpc.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True), \
                        patch.object(aria2_rpc.subprocess, "Popen", return_value=proc) as popen, \
                        patch.object(engine, "call", return_value={"version": "1.37.0"}):
                    engine.start()
                    engine.start()
                popen.assert_called_once()
                command = popen.call_args.args[0]
                kwargs = popen.call_args.kwargs
                for option in ("--enable-rpc", "--rpc-listen-all=false", f"--stop-with-process={os.getpid()}",
                               "--quiet=true", "--max-concurrent-downloads=2", "--seed-time=0",
                               "--bt-remove-unselected-file=true", "--file-allocation=none", "--auto-save-interval=30",
                               "--log-level=warn", "--no-conf=true"):
                    self.assertIn(option, command)
                self.assertIn(f"--rpc-secret={engine.secret}", command)
                self.assertIn(f"--rpc-listen-port={engine.port}", command)
                self.assertEqual(len(engine.secret), 32)  # token_urlsafe(24)
                self.assertEqual((kwargs["stdin"], kwargs["stdout"], kwargs["stderr"]),
                                 (subprocess.DEVNULL,) * 3)
                if system == "Windows":
                    self.assertEqual(kwargs["creationflags"], 0x08000000)
                    self.assertNotIn("start_new_session", kwargs)
                else:
                    self.assertTrue(kwargs["start_new_session"])
                    self.assertNotIn("creationflags", kwargs)

    def test_rpc_add_uri_and_multicall_authentication(self):
        response = Mock(status_code=200)
        response.json.side_effect = [{"result": "gid"}, {"result": [[{"status": "active"}],
                                                                       {"faultString": "gone"}]}]
        with patch.object(self.engine, "start"), patch.object(self.engine.session, "post", return_value=response) as post:
            self.assertEqual(self.engine.add_uri("magnet:test", self.root.name, (1, 2, 4)), "gid")
            values = post.call_args.kwargs
            self.assertEqual(values["timeout"], 3)
            self.assertFalse(values["allow_redirects"])
            self.assertEqual(values["json"]["params"], ["token:" + self.engine.secret, ["magnet:test"],
                                                         {"dir": self.root.name, "select-file": "1-2,4"}])
            statuses = self.engine.statuses(("one", "two"))
            self.assertEqual(statuses, ({"status": "active"}, {"status": "error", "errorMessage": "gone"}))
            body = post.call_args.kwargs["json"]
            self.assertEqual(body["method"], "system.multicall")
            self.assertEqual(body["params"], [[
                {"methodName": "aria2.tellStatus", "params": ["token:" + self.engine.secret, "one"]},
                {"methodName": "aria2.tellStatus", "params": ["token:" + self.engine.secret, "two"]},
            ]])

    def test_rpc_errors_invalid_json_and_redirects_are_clear(self):
        for code, payload, message in ((302, {}, "redirected"), (200, {}, "invalid"),
                                       (200, {"error": {"message": "bad secret"}}, "bad secret"),
                                       (200, [], "invalid")):
            with self.subTest(code=code, payload=payload):
                response = Mock(status_code=code)
                response.json.return_value = payload
                with patch.object(self.engine.session, "post", return_value=response):
                    with self.assertRaisesRegex(Aria2Error, message):
                        self.engine.call("aria2.getVersion")
        response.json.side_effect = ValueError("invalid JSON")
        with patch.object(self.engine.session, "post", return_value=response):
            with self.assertRaisesRegex(Aria2Error, "invalid"):
                self.engine.call("aria2.getVersion")

    def test_invalid_multicall_shape_raises_poll_failure(self):
        for result in ([], [["bad"]], "bad"):
            with self.subTest(result=result), patch.object(self.engine, "call", return_value=result):
                with self.assertRaisesRegex(Aria2Error, "invalid"):
                    self.engine.statuses(("one",))

    def test_remove_and_remove_result_are_distinct_rpc_calls(self):
        with patch.object(self.engine, "call") as call:
            self.engine.remove("one")
            self.engine.remove_result("two")
        self.assertEqual(call.call_args_list[0].args, ("aria2.remove", "one"))
        self.assertEqual(call.call_args_list[1].args, ("aria2.removeDownloadResult", "two"))

    def test_shutdown_escalates_shutdown_force_shutdown_tree_kill_and_reaps(self):
        proc = Mock()
        proc.poll.return_value = None
        proc.wait.side_effect = [subprocess.TimeoutExpired("aria2c", 5),
                                 subprocess.TimeoutExpired("aria2c", 3), 0]
        self.engine.proc = proc
        events = []
        with patch.object(self.engine, "call", side_effect=lambda method: events.append(method)), \
                patch.object(aria2_rpc, "_kill_process_tree", side_effect=lambda p: events.append("kill")) as kill:
            self.engine.shutdown()
            self.engine.shutdown()
        self.assertEqual(events, ["aria2.shutdown", "aria2.forceShutdown", "kill"])
        kill.assert_called_once_with(proc)
        self.assertEqual(proc.wait.call_args.kwargs, {"timeout": 5})
        with self.assertRaisesRegex(Aria2Error, "closed"):
            self.engine.start()

    def test_shutdown_returns_after_graceful_exit(self):
        proc = Mock()
        proc.poll.side_effect = [None, 0, 0]
        self.engine.proc = proc
        with patch.object(self.engine, "call") as call, patch.object(aria2_rpc, "_kill_process_tree") as kill:
            self.engine.shutdown()
        call.assert_called_once_with("aria2.shutdown")
        kill.assert_not_called()

    def test_second_ctrl_c_during_final_reap_still_waits_for_exit(self):
        proc = Mock()
        proc.poll.return_value = None
        proc.wait.side_effect = [subprocess.TimeoutExpired("aria2c", 5),
                                 subprocess.TimeoutExpired("aria2c", 3), KeyboardInterrupt(), 0]
        self.engine.proc = proc
        with patch.object(self.engine, "call"), patch.object(aria2_rpc, "_kill_process_tree"):
            self.engine.shutdown()
        self.assertEqual(proc.wait.call_count, 4)

    def test_fast_shutdown_skips_graceful_request(self):
        proc = Mock()
        proc.poll.side_effect = [None, 0, 0]
        self.engine.proc = proc
        with patch.object(self.engine, "call") as call:
            self.engine.shutdown(graceful=False)
        call.assert_called_once_with("aria2.forceShutdown")

    def test_shutdown_continues_after_rpc_failure_or_ctrl_c(self):
        for error in (requests.ConnectionError("gone"), KeyboardInterrupt()):
            with self.subTest(error=error):
                engine = Aria2Engine(state_dir=self.root.name)
                self.addCleanup(engine.session.close)
                proc = Mock()
                proc.poll.return_value = None
                engine.proc = proc
                with patch.object(engine, "call", side_effect=error) as call, \
                        patch.object(aria2_rpc, "_kill_process_tree") as kill:
                    engine.shutdown()
                self.assertEqual(call.call_count, 2)
                kill.assert_called_once_with(proc)

    def test_dead_process_and_never_started_shutdown_do_not_probe_with_os_kill(self):
        with patch("os.kill", side_effect=AssertionError("unsafe probe")):
            self.assertFalse(self.engine.is_alive())
            self.engine.shutdown()

    def test_bind_failure_retries_and_reaps_first_process(self):
        failed, good = Mock(), Mock()
        failed.poll.return_value = 1
        good.poll.return_value = None
        with patch.object(aria2_rpc.subprocess, "Popen", side_effect=[failed, good]) as popen, \
                patch.object(self.engine, "call", return_value={"version": "1.37.0"}):
            self.engine.start()
        self.assertEqual(popen.call_count, 2)
        failed.wait.assert_called_once_with(timeout=5)
        self.assertIs(self.engine.proc, good)

    def test_start_failure_is_translated_and_does_not_leave_a_process(self):
        with patch.object(aria2_rpc.subprocess, "Popen", side_effect=FileNotFoundError("missing")):
            with self.assertRaisesRegex(Aria2Error, "Could not start aria2c"):
                self.engine.start()
        self.assertIsNone(self.engine.proc)
        self.engine.shutdown()

    def test_background_unpack_uses_hidden_windows_console_only(self):
        for os_name in ("nt", "posix"):
            with self.subTest(os_name=os_name), patch.object(unpack.os, "name", os_name), \
                    patch.object(subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True), \
                    patch.object(unpack.subprocess, "run") as run:
                unpack._run(["tool", "archive"])
                kwargs = run.call_args.kwargs
                self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
                self.assertTrue(kwargs["capture_output"])
                self.assertEqual(kwargs["timeout"], unpack._TOOL_TIMEOUT)
                if os_name == "nt":
                    self.assertEqual(kwargs["creationflags"], 0x08000000)
                else:
                    self.assertNotIn("creationflags", kwargs)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class RealAria2Tests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("aria2c"), "aria2c is not on PATH")
    def test_local_http_download_exact_paths_and_no_process_left(self):
        with tempfile.TemporaryDirectory() as root:
            served = Path(root, "served")
            served.mkdir()
            payload = b"Torrent Finder background download\n" * 2048
            (served / "sample.bin").write_bytes(payload)
            target = Path(root, "download")
            target.mkdir()
            server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(served)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            engine = Aria2Engine(state_dir=os.path.join(root, "state"))
            real_popen = subprocess.Popen

            def offline_popen(command, **kwargs):
                # HTTP only: disable DHT bootstrap traffic for this no-internet
                # fixture, keeping every production process flag in the argv.
                return real_popen([*command, "--enable-dht=false", "--enable-dht6=false"], **kwargs)

            try:
                with patch.object(aria2_rpc.subprocess, "Popen", side_effect=offline_popen):
                    gid = engine.add_uri(f"http://127.0.0.1:{server.server_port}/sample.bin", str(target))
                deadline = time.monotonic() + 15
                status = {}
                while time.monotonic() < deadline:
                    status = engine.statuses((gid,))[0]
                    if status["status"] in ("complete", "error"):
                        break
                    time.sleep(.1)
                self.assertEqual(status.get("status"), "complete", status)
                paths = [f["path"] for f in status["files"] if f["selected"] == "true"]
                self.assertEqual([os.path.normcase(os.path.abspath(p)) for p in paths],
                                 [os.path.normcase(str(target / "sample.bin"))])
                self.assertEqual(Path(paths[0]).read_bytes(), payload)
                engine.remove_result(gid)
            finally:
                try:
                    engine.shutdown()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(3)
            self.assertIsNotNone(engine.proc)
            self.assertIsNotNone(engine.proc.poll(), "aria2c must be reaped before deleting the temp folder")
            self.assertFalse(thread.is_alive())
