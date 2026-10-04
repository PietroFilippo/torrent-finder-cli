"""Capture the interactive screens as plain text, and compare two captures.

    python scripts/ui_snapshots.py capture before      # writes %TEMP%/tf-ui-snapshots/before/
    python scripts/ui_snapshots.py capture after
    python scripts/ui_snapshots.py compare before after
    python scripts/ui_snapshots.py check after        # overflow only, every size

Each scenario opens a real screen with every key press answered by Ctrl+C, so
a screen draws its first frame and then backs out. Frames are recorded at a
few terminal sizes. ``compare`` lists, per screen and size, the words the
first capture showed that the second no longer shows, and any frame that is
taller or wider than its terminal. Words removed on purpose (emoji, the old
banner text) are listed in ``EXPECTED_GONE``.

Saved settings, credentials and downloads are redirected to a temporary folder
by ``tests/isolation.py``; nothing touches the user's real data or the network.
"""

from __future__ import annotations

import io

import random
import re
import sys
import tempfile

import traceback
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import isolation  # noqa: E402,F401  # redirects persistence before anything loads it
import readchar  # noqa: E402

from torrent_finder.constants import console  # noqa: E402

SIZES = [(40, 12), (50, 16), (80, 24), (120, 40)]
OUT = Path(tempfile.gettempdir()) / "tf-ui-snapshots"
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[=>78]")
HOME = re.compile(r"\x1b\[H|\x1b\[1;1H")
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'+.-]*[A-Za-z0-9]|[A-Za-z0-9]")

# Words the redesign removes on purpose; not reported as missing.
EXPECTED_GONE = {"cli"}


class _Cancel(Exception):
    pass


def _cancel_key(*_args, **_kwargs):
    raise KeyboardInterrupt


def _sample_results():
    from torrent_finder.search_result import SearchResult
    now = 1_789_000_000  # fixed, so captures taken on different days compare equal
    rows = [
        ("Dune Part Two 2024 1080p WEB-DL DDP5.1 Atmos H.264-FLUX", "Apibay", 1843, 212, 7_900_000_000, 30),
        ("Dune.Part.Two.2024.2160p.UHD.BluRay.x265.HDR.DV.TrueHD.7.1-B0MBARDiERS", "Knaben", 920, 140, 24_000_000_000, 20),
        ("Dune Part Two (2024) [1080p] [WEBRip] [5.1] [YTS.MX]", "YTS", 3310, 400, 2_300_000_000, 25),
        ("Dune.Parte.Dois.2024.1080p.WEB-DL.DUAL.5.1.Dublado.PT-BR", "Apibay", 410, 70, 4_100_000_000, 12),
        ("Dune 2021 1080p BluRay x264-SPARKS", "Knaben", 220, 30, 9_800_000_000, 400),
        ("Dune Part Two 2024 720p HDCAM x264 AAC", "Apibay", 12, 9, 1_200_000_000, 200),
        ("Dune.Part.Two.2024.1080p.AMZN.WEB-DL.DDP5.1.H.264-FLUX", "Knaben", 0, 2, 7_700_000_000, 2),
    ]
    results = []
    for i, (name, source, seeds, leeches, size, age) in enumerate(rows):
        extra = {"knaben_tracker": "1337x"} if source == "Knaben" else {}
        results.append(SearchResult(name=name, info_hash=f"{i:040x}", seeders=seeds, leechers=leeches,
                                    size=size, source=source, extra=extra, uploaded_at=now - 86400 * age))
    return results


def _combined_results():
    rows = _sample_results()
    labels = [("movies", "Movies & Series"), ("anime", "Anime"), ("manga", "Manga · General")]
    for i, row in enumerate(rows):
        slug, label = labels[i % 3]
        row["provider_slug"] = slug
        row["provider_label"] = label
        row["from_work"] = "Dune" if i % 2 else "Dune Part Two"
    return rows


def _seed_state():
    from torrent_finder.state import add_history_entry
    from torrent_finder.stats import record_method_pick, record_search, record_torrent_picked
    for query, slug in [("dune part two", "movies"), ("the matrix", "movies"), ("frieren", "anime"),
                        ("berserk", "manga"), ("elden ring", "games")]:
        add_history_entry(query, slug, [])
        record_search(slug, query, [])
    record_torrent_picked("movies", 920)
    record_method_pick("open_magnet")
    try:
        from torrent_finder import bookmarks
        from torrent_finder.providers import PROVIDERS
        bookmarks.save_results(PROVIDERS[0], _sample_results()[:2])
        bookmarks.save_search(PROVIDERS[0], "dune")
    except Exception:  # bookmarks are a nicety for the capture
        traceback.print_exc()


def _scenarios():
    """(name, callable) pairs; each opens one screen (sometimes a short chain)."""
    from torrent_finder.providers import GAMES_GROUP, MANGA_GROUP, PROVIDERS, SOFTWARE_GROUP, get_provider
    from torrent_finder.ui import prompts
    from torrent_finder.torrent_meta import TorrentFile

    movie = get_provider("movies")
    anime = get_provider("anime")
    combined = get_provider("all")

    def search_editor(provider, notice="", committed=()):
        def run():
            renderer = prompts.make_search_screen_renderer(
                ", ".join(e.name for e in provider.effective_engines) or "None",
                provider.filter_summary(), has_history=True, notice=notice,
            )
            prompts.get_query_with_shortcut(
                f"[title] Search {provider.name}:[/title] ", initial="dune", history=["dune"],
                filters_shortcut=True, multi=True, screen_renderer=renderer)
        return run

    def table(results, note=""):
        def run():
            from torrent_finder.ui.table import interactive_select
            interactive_select(results, note=note, search_summary="Prefer 1080p")
        return run

    def info_screen():
        from torrent_finder.torrent_info import TorrentInfo
        info = TorrentInfo(source="Nyaa", title="[SubsPlease] Frieren - 01 (1080p)", category="Anime - English",
                           uploader="SubsPlease", date="2026-09-14", seeders="920", leechers="140", size="1.4 GiB",
                           info_hash="ab" * 20, description="Frieren episode one.\nSecond line of text.",
                           files=[("[SubsPlease] Frieren - 01 (1080p).mkv", "1.4 GiB")], embedded_subs="English (ASS)")
        with patch("torrent_finder.torrent_info.fetch_torrent_info", return_value=(info, "")):
            prompts.torrent_info_screen({"source": "Nyaa"})

    def security():
        from torrent_finder import security as sec
        with patch.object(sec, "_fetch_network_info", return_value={
                "query": "203.0.113.7", "isp": "Example ISP", "org": "Example Org",
                "as": "AS64500 Example", "country": "Brazil"}):
            sec.show_security_warning(force=True)

    def stream_header():
        from torrent_finder.ui import streaming
        streaming._print_stream_header(1, 3, 2, True, vlc_url="http://localhost:8888/0",
                                       use_scroll_region=False, sub_paths=["/tmp/ep01.en.srt"],
                                       backend="webtorrent", filename="Frieren - 01 (1080p).mkv",
                                       filesize_bytes=1_500_000_000)

    def update_view(stage):
        def run():
            from torrent_finder.ui.update_progress import UpdateView, update_panel
            console.print(update_panel(UpdateView(stage=stage, detail="Installing torrent-finder-cli 0.8.2.",
                                                  current="0.8.1", latest="0.8.2"), 12.0,
                                       width=min(72, console.size.width)))
        return run

    files = [TorrentFile(i, f"Show/Show - {i:02d} (1080p).mkv", 1_400_000_000) for i in range(1, 13)]
    files.append(TorrentFile(13, "Show/readme.txt", 1_000))

    scenarios = [
        ("provider-menu", lambda: prompts.provider_select_prompt(update_available=True)),
        ("provider-menu-exit-armed", lambda: prompts.provider_select_prompt(
            notice="[not dim bold yellow]Press Esc or Ctrl+C again to quit[/not dim bold yellow]")),
        ("group-games", lambda: prompts._provider_group_menu(GAMES_GROUP)),
        ("group-software", lambda: prompts._provider_group_menu(SOFTWARE_GROUP)),
        ("group-manga", lambda: prompts._provider_group_menu(MANGA_GROUP)),
        ("source-anime", lambda: prompts._provider_source_menu(anime, anime.creator_facets)),
        ("quick-actions-provider", lambda: prompts.quick_actions_menu(True, movie)),
        ("quick-actions-global", lambda: prompts.quick_actions_menu(False, None)),
        ("action-provider", lambda: prompts.action_provider_prompt("Bookmarks")),
        ("episode-picker", lambda: prompts.episode_select_prompt(files, [1, 2, 3])),
        ("subtitle-source", lambda: prompts.subtitle_source_prompt()),
        ("download-folder", lambda: prompts.download_dir_prompt()),
        ("confirm", lambda: prompts.confirm_prompt("Exit Torrent Finder?", title="Exit")),
        ("download-method", lambda: prompts.download_method_prompt(
            magnet="magnet:?xt=urn:btih:" + "ab" * 20, show_subtitles=True, show_episode_picker=True,
            selected_indexes=None, show_streaming=True, page_url="https://nyaa.si/view/1", info_source="Nyaa")),
        ("download-method-selection", lambda: prompts.download_method_prompt(
            magnet="magnet:?xt=urn:btih:" + "ab" * 20, show_subtitles=True, show_episode_picker=True,
            selected_indexes=[1, 2, 3, 7], show_streaming=True, page_url="https://nyaa.si/view/1",
            info_source="Nyaa", sub_choice={"mode": "external", "paths": ["/tmp/a.srt", "/tmp/b.srt"]})),
        ("download-method-plain", lambda: prompts.download_method_prompt(
            magnet="magnet:?xt=urn:btih:" + "ab" * 20, show_subtitles=False, show_streaming=False)),
        ("batch-menu", lambda: prompts.batch_download_menu(3, 3)),
        ("credentials", lambda: prompts.credentials_menu()),
        ("download-complete", lambda: prompts.download_complete_prompt("Download finished", summary="Saved to /tmp/x")),
        ("whats-next", lambda: prompts.search_again_prompt()),
        ("torrent-info", info_screen),
        ("search-editor", search_editor(movie)),
        ("search-editor-notice", search_editor(movie, notice="[warning] No results found.[/warning]")),
        ("search-editor-combined", search_editor(combined)),
        ("results", table(_sample_results())),
        ("results-notices", table(_sample_results(), note="Apibay: request timed out\nKnaben: blocked by anti-bot check\nYTS: no rows")),
        ("results-combined", table(_combined_results(), note="Madokami: not logged in")),
        ("results-empty", table([])),
        ("security-warning", security),
        ("stream-header", stream_header),
        ("update-installing", update_view("installing")),
        ("update-failed", update_view("failed")),
    ]
    for p in PROVIDERS:
        scenarios.append((f"filters-{p.slug}", (lambda p=p: prompts.filter_menu(p))))

    def lazy(module, name, *args):
        def run():
            mod = __import__(module, fromlist=[name])
            getattr(mod, name)(*args)
        return run

    scenarios += [
        ("history", lazy("torrent_finder.ui.history", "history_select_prompt")),
        ("stats", lazy("torrent_finder.ui.stats", "stats_page")),
        ("tips", lazy("torrent_finder.ui.tips_page", "tips_page")),
        ("bookmarks", lazy("torrent_finder.ui.bookmarks", "bookmark_menu")),
        ("backup", lazy("torrent_finder.ui.backup", "backup_menu")),
        ("qbittorrent", lazy("torrent_finder.ui.qbittorrent", "client_menu")),
        ("refine", lazy("torrent_finder.ui.result_filters", "refine_results", "", "contains", "relevance")),
        ("sort", lazy("torrent_finder.ui.result_filters", "choose_result_sort", "relevance")),
        ("terminal-command", lazy("torrent_finder.ui.launcher", "terminal_command_prompt")),
        ("search-notices", lazy("torrent_finder.ui.table", "_show_search_notices",
                                "Apibay: request timed out\nKnaben: blocked by anti-bot check")),
    ]

    def name_rules():
        from torrent_finder.name_rules import NameRules
        from torrent_finder.ui.name_rules import edit_name_rules
        edit_name_rules(NameRules())

    scenarios.append(("name-rules", name_rules))
    return scenarios


def _frames(raw: str) -> list[str]:
    frames = []
    for chunk in HOME.split(raw):
        text = ANSI.sub("", chunk).replace("\r", "")
        lines = [line.rstrip() for line in text.split("\n")]
        while lines and not lines[-1]:
            lines.pop()
        while lines and not lines[0]:
            lines.pop(0)
        if lines:
            frames.append("\n".join(lines))
    return frames


def capture(label: str) -> None:
    out_dir = OUT / label
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.txt"):
        old.unlink()
    _seed_state()
    report = []
    for width, height in SIZES:
        for name, run in _scenarios():
            random.seed(7)
            buffer = io.StringIO()
            with ExitStack() as stack:
                stack.enter_context(patch.object(readchar, "readkey", _cancel_key))
                stack.enter_context(patch("sys.stdout", buffer))
                stack.enter_context(patch("os.system", lambda *_a: 0))
                stack.enter_context(patch.object(console, "_force_terminal", True))
                stack.enter_context(patch.object(console, "_color_system", None))
                stack.enter_context(patch.object(console, "is_interactive", True))
                stack.enter_context(patch.object(console, "legacy_windows", False))
                stack.enter_context(patch.object(type(console), "size", property(
                    lambda _self, w=width, h=height: __import__("rich.console").console.ConsoleDimensions(w, h))))
                try:
                    run()
                    status = "ok"
                except (KeyboardInterrupt, EOFError, _Cancel):
                    status = "ok"
                except Exception as error:  # a scenario that cannot run is reported, not fatal
                    status = f"error: {type(error).__name__}: {error}"
            frames = _frames(buffer.getvalue())
            path = out_dir / f"{name}@{width}x{height}.txt"
            separator = "\n\n" + SEPARATOR + "\n\n"
            path.write_text(separator.join(frames), encoding="utf-8")
            report.append(f"{name:<32} {width}x{height}  frames={len(frames)}  {status}")
    (out_dir / "_report.log").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))
    print(f"\n{len(report)} captures in {out_dir}")


def _words(text: str) -> set[str]:
    return {w.casefold() for w in WORD.findall(text)}


SEPARATOR = "=" * 20 + " next frame " + "=" * 20


def _overflow(text: str, width: int, height: int) -> list[str]:
    """Frames of a capture that are taller or wider than their terminal."""
    from rich.cells import cell_len
    problems = []
    for i, frame in enumerate(text.split(SEPARATOR)):
        lines = frame.strip("\n").split("\n")
        if len(lines) > height:
            problems.append(f"frame {i}: {len(lines)} rows > {height}")
        wide = [cell_len(line) for line in lines if cell_len(line) > width]
        if wide:
            problems.append(f"frame {i}: {max(wide)} cols > {width}")
    return problems


def _size(name: str) -> tuple[int, int]:
    match = re.search(r"@(\d+)x(\d+)", name)
    return int(match.group(1)), int(match.group(2))


def check(label: str) -> int:
    """Report every frame in one capture that overflows its terminal."""
    problems = 0
    for path in sorted((OUT / label).glob("*.txt")):
        found = _overflow(path.read_text(encoding="utf-8"), *_size(path.name))
        if found:
            problems += 1
            print(f"--- {path.name}")
            for line in found:
                print("    " + line)
    print(f"\n{problems} capture(s) overflow")
    return problems


def compare(before: str, after: str) -> int:
    a_dir, b_dir = OUT / before, OUT / after
    problems = 0
    for path in sorted(a_dir.glob("*.txt")):
        other = b_dir / path.name
        if not other.exists():
            print(f"[missing capture] {path.name}")
            problems += 1
            continue
        old_text = path.read_text(encoding="utf-8")
        new_text = other.read_text(encoding="utf-8")
        gone = sorted(_words(old_text) - _words(new_text) - EXPECTED_GONE)
        overflow = _overflow(new_text, *_size(path.name))
        if gone or overflow:
            problems += 1
            print(f"--- {path.name}")
            if gone:
                print("    words no longer shown: " + ", ".join(gone))
            for line in overflow:
                print("    " + line)
    print(f"\n{problems} capture(s) to review")
    return problems


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "capture":
        capture(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == "compare":
        compare(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 3 and sys.argv[1] == "check":
        check(sys.argv[2])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
