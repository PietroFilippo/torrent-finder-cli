import hashlib
import json
import threading
import unittest
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import requests

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from torrent_finder import acquisition, qbittorrent as qb
from torrent_finder.ui.qbittorrent import progress_text
from torrent_finder.ui import qbittorrent as ui


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.calls, self.rows = [], {}
        self.fail_login = False
        test = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                test.calls.append((self.path, body, dict(self.headers)))
                if self.path.endswith("/auth/login"):
                    self.send_response(200)
                    self.send_header("Set-Cookie", "SID=test-session; Path=/")
                    self.end_headers()
                    self.wfile.write(b"Fails." if test.fail_login else b"Ok.")
                    return
                if self.headers.get("Cookie") != "SID=test-session":
                    self.send_error(403)
                    return
                if self.path.endswith("/torrents/add"):
                    values = parse_qs(body.decode())
                    payload = qb.magnet_payload(values["urls"][0])
                    test.rows[payload.info_hash] = dict(hash=payload.info_hash, name="Test torrent",
                        progress=0.25, state="downloading", downloaded=1024, dlspeed=128,
                        eta=60, save_path=values.get("savepath", ["default"])[0],
                        category=values.get("category", [""])[0])
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"Ok.")

            def do_GET(self):
                test.calls.append((self.path, b"", dict(self.headers)))
                if self.headers.get("Cookie") != "SID=test-session":
                    self.send_error(403)
                    return
                parsed = urlsplit(self.path)
                if parsed.path.endswith("/app/version"):
                    content = b"v5.1.2"
                elif parsed.path.endswith("/torrents/categories"):
                    content = b'{"Anime": {"name":"Anime","savePath":"/media/anime"}}'
                else:
                    hashes = parse_qs(parsed.query).get("hashes", [""])[0].split("|")
                    rows = [r for h, r in test.rows.items() if hashes == [""] or h in hashes]
                    content = json.dumps(rows).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(content)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = qb.Client(f"http://127.0.0.1:{self.server.server_port}", "user", "test-password")

    def tearDown(self):
        self.client.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_cookie_handoff_folder_category_duplicate_and_actual_progress(self):
        self.assertEqual(self.client.connect(), "v5.1.2")
        self.assertIn("Anime", self.client.categories())
        payload = qb.magnet_payload("magnet:?xt=urn:btih:" + "a" * 40)
        self.assertEqual(self.client.add(payload, "/remote/folder", "Anime"), "added to client")
        self.assertEqual(self.client.add(payload, "/different", ""), "already in client")
        row = self.client.torrents([payload.info_hash])[0]
        self.assertEqual(row["save_path"], "/remote/folder")
        self.assertEqual(row["category"], "Anime")
        self.assertIn("25.0%", progress_text(row))
        adds = [c for c in self.calls if "/torrents/add" in c[0]]
        self.assertEqual(len(adds), 1)
        self.assertIn(b"autoTMM=false", adds[0][1])
        self.assertTrue(all("/api/v2/" in c[0] for c in self.calls))

    def test_rejected_login_does_not_send_or_claim_connected(self):
        self.fail_login = True
        with self.assertRaises(qb.ClientError) as failure:
            self.client.connect()
        self.assertNotIn("test-password", str(failure.exception))
        self.assertEqual(len(self.calls), 1)


class PayloadAndFailureTests(unittest.TestCase):
    def test_url_validation_and_reverse_proxy_prefix(self):
        self.assertEqual(qb.normalize_url("https://example.test/qbit/"), "https://example.test/qbit")
        for value in ("ftp://host", "http://user:password@host", "http://host?password=x",
                      "http://host#x", "http://host:bad", "", "http://ho st"):
            with self.subTest(value=value), self.assertRaises(qb.ClientError):
                qb.normalize_url(value)

    def test_base32_and_hex_identity(self):
        self.assertEqual(qb.magnet_payload("magnet:?xt=urn:btih:" + "A" * 32).info_hash, "0" * 40)
        self.assertEqual(qb.magnet_payload("magnet:?xt=urn:btih:" + "A" * 40).info_hash, "a" * 40)
        with self.assertRaises(qb.ClientError):
            qb.magnet_payload("magnet:?xt=urn:btih:source-placeholder")

    def test_torrent_hash_uses_original_info_bytes(self):
        info = b"d4:name4:test6:lengthi4e12:piece lengthi4e6:pieces20:abcdefghijklmnopqrste"
        data = b"d8:announce19:http://tracker.test4:info" + info + b"e"
        payload = qb.torrent_payload(data)
        self.assertEqual(payload.info_hash, hashlib.sha1(info).hexdigest())
        self.assertEqual(payload.data, data)
        for bad in (b"<html>blocked</html>", data[:-1], b"de", b"d4:infodee"):
            with self.subTest(bad=bad), self.assertRaises(qb.ClientError):
                qb.torrent_payload(bad)

    def test_no_mutation_retry_after_timeout_and_no_redirects(self):
        session = Mock()
        session.request.side_effect = requests.Timeout("sensitive-address")
        client = qb.Client("http://localhost:8080", session=session)
        with patch.object(client, "torrents", return_value=[]):
            with self.assertRaisesRegex(qb.ClientError, "unknown"):
                client.add(qb.TorrentPayload("a" * 40, "magnet:test"))
        self.assertEqual(session.request.call_count, 1)
        self.assertFalse(session.request.call_args.kwargs["allow_redirects"])
        self.assertEqual(session.request.call_args.kwargs["timeout"], 8)

    def test_acknowledgement_without_client_state_is_pending(self):
        session = Mock()
        session.request.return_value = Mock(status_code=200, text="Ok.")
        client = qb.Client("http://localhost:8080", session=session)
        with patch.object(client, "torrents", return_value=[]):
            self.assertEqual(client.add(qb.TorrentPayload("a" * 40, "magnet:test")), "submitted; confirmation pending")

    def test_invalid_json_and_redirect_are_failures(self):
        session = Mock()
        client = qb.Client("http://localhost:8080", session=session)
        session.request.return_value = Mock(status_code=200)
        session.request.return_value.json.side_effect = ValueError()
        with self.assertRaises(qb.ClientError):
            client.torrents()
        session.request.return_value = Mock(status_code=302)
        with self.assertRaises(qb.ClientError):
            client.connect()

    def test_torrent_upload_uses_multipart(self):
        session = Mock()
        session.request.return_value = Mock(status_code=200, text="Ok.")
        client = qb.Client("http://localhost:8080", session=session)
        with patch.object(client, "torrents", side_effect=[[], [{"hash": "a" * 40}]]):
            client.add(qb.TorrentPayload("a" * 40, data=b"metadata"))
        self.assertEqual(session.request.call_args.kwargs["files"]["torrents"][1], b"metadata")

    def test_acquisition_keeps_direct_downloads_out_and_resolves_lazy_magnets(self):
        for source in ("Madokami", "Libgen"):
            self.assertFalse(hasattr(acquisition.for_result({"source": source}), "client_payload"))
        with patch("torrent_finder.fitgirl.resolve_info_hash", return_value="a" * 40):
            result = {"source": "FitGirl", "info_hash": "placeholder", "fg_post_url": "https://example.test"}
            self.assertEqual(acquisition.for_result(result).client_payload(result).info_hash, "a" * 40)

    def test_verifier_closes_connection_and_keeps_errors_generic(self):
        with patch.object(qb, "Client") as cls:
            cls.return_value.connect.return_value = "v5.0.0"
            self.assertTrue(qb.verify({"QBITTORRENT_URL": "http://localhost"})[0])
            cls.return_value.close.assert_called_once()

    def test_cancel_destination_never_submits(self):
        client = Mock()
        client.connect.return_value = "v5.0.0"
        client.categories.return_value = {}
        with patch.object(ui.Client, "from_settings", return_value=client), \
             patch.object(ui, "_read", side_effect=lambda fn, _: fn()), \
             patch.object(ui, "arrow_select", return_value=None):
            self.assertFalse(ui.send_results([{"source": "Nyaa", "info_hash": "a" * 40}]))
        client.add.assert_not_called()
        client.close.assert_called_once()

    def test_mixed_batch_skips_direct_files_and_reports_existing_without_completion(self):
        client = Mock()
        client.connect.return_value = "v5.0.0"
        client.categories.return_value = {}
        client.add.return_value = "already in client"
        rows = [{"source": "Nyaa", "info_hash": "a" * 40, "name": "Torrent"},
                {"source": "Madokami", "name": "Direct file"}]
        with patch.object(ui.Client, "from_settings", return_value=client), \
             patch.object(ui, "_read", side_effect=lambda fn, _: fn()), \
             patch.object(ui, "arrow_select", return_value=2), \
             patch.object(ui, "start_esc_listener", return_value=threading.Event()), \
             patch.object(ui.console, "status", return_value=nullcontext()), \
             patch.object(ui, "read_details") as notice, patch.object(ui, "show_progress"):
            self.assertTrue(ui.send_results(rows))
        client.add.assert_called_once()
        self.assertIn("already in client", notice.call_args.args[0])
        self.assertIn("Skipped 1", notice.call_args.args[0])
        self.assertNotIn("completed", notice.call_args.args[0])

    def test_stopped_batch_cannot_start_a_later_submission(self):
        client = Mock()
        client.categories.return_value = {}
        def stop(cancel):
            cancel.set()
            return threading.Event()
        with patch.object(ui.Client, "from_settings", return_value=client), \
             patch.object(ui, "_read", side_effect=lambda fn, _: fn()), \
             patch.object(ui, "arrow_select", return_value=2), \
             patch.object(ui, "start_esc_listener", side_effect=stop), \
             patch.object(ui.console, "status", return_value=nullcontext()), \
             patch.object(ui, "read_details"):
            self.assertFalse(ui.send_results([{"source": "Nyaa", "info_hash": "a" * 40}]))
        client.add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
