"""Downloads speak at display time while tool and public values keep their identities."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import isolation  # noqa: F401 — isolate settings before importing the app
from rich.console import Console
from rich.text import Text

from torrent_finder import acquisition, downloader, i18n, jimaku, subtitles, torrent_info, unpack
from torrent_finder.torrent_session import TorrentSession
from torrent_finder.ui import streaming, theme


class DownloadsLanguageTests(unittest.TestCase):
    def setUp(self):
        previous = i18n.current()
        self.addCleanup(i18n.use, previous)
        i18n.use("pt-BR")

    def test_torrent_verdict_and_error_values_stay_english(self):
        with patch.object(torrent_info, "_locate_local_video", return_value="movie.mkv"), \
             patch.object(torrent_info, "_ffprobe_subtitle_tracks", return_value=["por/ass", "eng/srt"]):
            verdict = torrent_info.assess_embedded_subs({"name": "movie.mkv"}, [])
        self.assertEqual(verdict, "yes — 2 embedded track(s): por/ass, eng/srt (ffprobe)")
        self.assertEqual(torrent_info.info_label(verdict), "sim — 2 faixas embutidas: por/ass, eng/srt (ffprobe)")
        _, reason = torrent_info.fetch_torrent_info({"source": "Other"})
        self.assertEqual(reason, "Origin info isn't available for Other.")
        self.assertEqual(torrent_info.info_label(reason), "Informações da origem indisponíveis para Other.")
        self.assertEqual(torrent_info.info_label("Couldn't reach Nyaa (Timeout)."),
                         "Não foi possível acessar Nyaa (Timeout).")
        self.assertEqual(torrent_info.description_label("IMDb rating: 8.2/10\n\nOriginal description [tag]"),
                         "Nota no IMDb: 8.2/10\n\nOriginal description [tag]")

    def test_ffprobe_fields_and_command_stay_unchanged_in_each_language(self):
        streams = [
            {"codec_type": "video", "codec_name": "h264"},
            {"codec_type": "subtitle", "codec_name": "ass", "tags": {"language": "por"}},
            {"codec_type": "subtitle", "codec_name": "srt", "tags": None},
            {"codec_type": "subtitle", "codec_name": "ass"},
        ]
        for language in ("en", "pt-BR", "qps"):
            with self.subTest(language=language):
                i18n.use(language)
                with patch.object(torrent_info.subprocess, "run",
                                  return_value=Mock(stdout=json.dumps({"streams": streams}))) as run:
                    tracks = torrent_info._ffprobe_subtitle_tracks("Show [BR].mkv")
                self.assertEqual(tracks, ["por/ass", "und/srt", "und/ass"])
                self.assertEqual(run.call_args.args[0],
                                 ["ffprobe", "-v", "quiet", "-print_format", "json",
                                  "-show_streams", "Show [BR].mkv"])

    def test_verification_values_stay_english_until_display(self):
        result = subtitles.test_addic7ed("user", "password")
        self.assertEqual(result, (None, "Addic7ed can't be verified automatically; it'll be used on the next search."))
        self.assertIn("próxima busca", subtitles.verification_label(result[1]))
        with patch.object(jimaku.requests, "get") as get:
            get.return_value.status_code = 401
            result = jimaku.validate_key("key")
        self.assertEqual(result, (False, "Invalid API key (401)"))
        self.assertEqual(jimaku.verification_label(result[1]), "Chave de API inválida (401)")
        for label in (jimaku.verification_label, subtitles.verification_label):
            self.assertEqual(label("Couldn't verify (HTTP 429)"), "Não foi possível verificar (HTTP 429)")

    def test_kept_reasons_and_batch_notes_stay_english(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "book.rar")
            with patch.object(unpack.zipfile, "is_zipfile", return_value=False), \
                 patch.object(unpack, "_tool_reader", return_value=None), \
                 patch.object(unpack, "_tools", return_value=[]):
                _, reason = unpack.unpack(path, expect_pages=True)
            self.assertEqual(reason, "no program here opens .rar files; install 7-Zip or UnRAR")
            report = unpack.Report(kept=[(path, reason)])
            self.assertIn("instale 7-Zip ou UnRAR", Text.from_markup(unpack.summary_lines(report)[0]).plain)
            status = Mock()
            with patch("torrent_finder.madokami.download_file", return_value=path), \
                 patch.object(unpack, "enabled", return_value=True), \
                 patch.object(unpack, "unpack_all", return_value=report):
                outcome = acquisition.MadokamiAcquisition().batch_item(
                    {"mdk_path": "/book.rar"}, download_dir=directory,
                    cancel_event=None, set_status=status)
            status.assert_called_once_with("descompactando")
            self.assertEqual(outcome.note, f"Kept book.rar packed: {reason}")
            self.assertIn("Mantido compactado: book.rar", outcome.note_label())
            self.assertEqual(report.kept[0][1], reason)

    def test_client_and_session_state_identities(self):
        with patch.object(downloader.platform, "system", return_value="Linux"), \
             patch.object(downloader.shutil, "which", return_value=None):
            client = downloader.detect_torrent_client()
        self.assertEqual(client, "default torrent client")
        self.assertEqual(downloader.torrent_client_label(client), "cliente de torrent padrão")
        self.assertEqual(downloader.torrent_client_label("qBittorrent"), "qBittorrent")
        session = TorrentSession({}, "magnet:?xt=urn:btih:" + "ab" * 20)
        with patch("torrent_finder.torrent_session.fetch_file_list", return_value=None):
            session.fetch_files_meta()
        self.assertEqual(session.files_meta_status, "unavailable")
        self.assertEqual(session.name, "Unknown")

    def test_aria_command_and_plural_display(self):
        for indexes, expected in (([1], "(1 arquivo)"), ([1, 3], "(2 arquivos)")):
            with self.subTest(indexes=indexes):
                output = io.StringIO()
                console = Console(file=output, width=120, force_terminal=False)
                with patch.object(downloader, "console", console), \
                     patch.object(downloader.shutil, "which", return_value="aria2c"), \
                     patch.object(downloader, "_download_dir_or_explain", return_value="folder [data]"), \
                     patch.object(downloader, "is_quiet_mode", return_value=True), \
                     patch.object(downloader, "_run_download", return_value=0) as run:
                    self.assertTrue(downloader.download_with_aria2("magnet:?xt=urn:btih:abc", indexes))
                self.assertIn(expected, output.getvalue())
                self.assertIn("folder [data]", output.getvalue())
                self.assertIn("--select-file=" + ",".join(map(str, indexes)), run.call_args.args[0])
                self.assertEqual(run.call_args.args[0][-1], "magnet:?xt=urn:btih:abc")
                self.assertIn("Ctrl+C cancelar", run.call_args.args[2])

    def test_npm_install_identity_is_used_before_translating(self):
        output = io.StringIO()
        with patch.object(downloader, "console", Console(file=output, width=160)), \
             patch.object(downloader.shutil, "which", return_value="C:/webtorrent.cmd"), \
             patch.object(downloader.os, "name", "nt"), \
             patch.object(downloader, "_unwrap_npm_shim", return_value=None):
            self.assertIsNone(downloader._cli_command("webtorrent"))
        self.assertIn("npm install -g webtorrent-cli", output.getvalue())
        self.assertIn("Reinstale", output.getvalue())
        self.assertEqual(downloader._NODE_CLI_INSTALL["webtorrent"].split(": ", 1)[-1],
                         "npm install -g webtorrent-cli")

    def test_node_download_commands_stay_unchanged_in_each_language(self):
        magnet = "magnet:?xt=urn:btih:" + "ab" * 20 + "&dn=Show%20[BR]"
        for language in ("en", "pt-BR", "qps"):
            i18n.use(language)
            for tool, download in (("webtorrent", downloader.download_with_webtorrent),
                                   ("peerflix", downloader.download_with_peerflix)):
                with self.subTest(language=language, tool=tool):
                    output = io.StringIO()
                    with patch.object(downloader, "console", Console(file=output, width=160)), \
                         patch.object(downloader, "_cli_command", return_value=["node", tool + ".js"]), \
                         patch.object(downloader, "_download_dir_or_explain", return_value="folder [BR]"), \
                         patch.object(downloader, "is_quiet_mode", return_value=True), \
                         patch.object(downloader, "_run_download", return_value=0) as run:
                        self.assertTrue(download(magnet, [1, 3]))
                    self.assertEqual(run.call_count, 2)
                    for call, index in zip(run.call_args_list, (0, 2)):
                        command, quiet, status = call.args
                        if tool == "webtorrent":
                            self.assertEqual(command, ["node", "webtorrent.js", "download", magnet,
                                                       "--out", "folder [BR]", "--select", str(index)])
                        else:
                            self.assertEqual(command[:6], ["node", "peerflix.js", magnet,
                                                          "--path", "folder [BR]", "--on-downloaded"])
                            self.assertEqual(command[-2:], ["-i", str(index)])
                            self.assertEqual(command[6], downloader._touch_command(call.kwargs["done_marker"]))
                        self.assertTrue(quiet)
                        self.assertIn("Ctrl+C", status)
                    self.assertIn("folder [BR]", output.getvalue())
                    if language == "en":
                        self.assertEqual(run.call_args_list[0].args[2],
                                         "[accent]Downloading…[/accent]  session 1/2  •  Ctrl+C cancel")
                        self.assertIn("Download complete!", output.getvalue())

    def test_stream_end_statuses_stay_english_and_logs_are_not_translated(self):
        output = io.StringIO()
        with patch.object(downloader, "console", Console(file=output, width=160)), \
             patch.object(downloader, "_log_tail", return_value="[error] tool output"):
            self.assertEqual(downloader._report_stream_end(0, ""), "ended")
            self.assertEqual(downloader._report_stream_end(1, "stream [BR].log"), "failed")
        self.assertIn("[error] tool output", output.getvalue())
        self.assertIn("stream [BR].log", output.getvalue())
        self.assertIn("Reprodução interrompida", output.getvalue())

    def test_keybars_are_parseable_in_each_language(self):
        for language in ("en", "pt-BR", "qps"):
            i18n.use(language)
            for english in ("Enter open • Esc back", "Ctrl+C cancel", "v reopen VLC", "n next", "b previous", "n/b next/prev"):
                self.assertEqual([key.plain.split()[0] for key in theme.parse_footer(i18n.t(english)).keys],
                                 [key.plain.split()[0] for key in theme.parse_footer(english).keys])

    def test_pseudo_header_escapes_filenames_and_wraps_its_ui(self):
        i18n.use("qps")
        output = io.StringIO()
        title = []
        with patch.object(streaming, "console", Console(file=output, width=80)), \
             patch.object(streaming, "_clear_terminal"), \
             patch.object(streaming, "_set_terminal_title", side_effect=title.append), \
             patch.object(streaming.sys, "stdout", io.StringIO()):
            streaming._print_stream_header(1, 3, 2, True, vlc_url="http://localhost:8888/0",
                                           filename="Show [Group].mkv", sub_paths=["sub [BR].ass", "eng.srt"],
                                           backend="peerflix", use_scroll_region=False)
        self.assertIn("Show [Group].mkv", output.getvalue())
        self.assertIn("sub [BR].ass", output.getvalue())
        self.assertIn("⟦", output.getvalue())
        self.assertIn("⟦", title[0])


if __name__ == "__main__":
    unittest.main()
