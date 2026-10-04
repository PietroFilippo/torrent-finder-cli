"""The acquisition seam: how a picked result becomes files on disk.

Four styles exist (see CONTEXT.md → "Acquisition"): magnet-direct,
magnet-lazy-resolve, torrent-file-handoff, and direct-download. Each is an
adapter here, and every consumer path — single pick, batch handoff, magnet
collection (copy / aria2) — drives the same small interface instead of
re-testing ``result["source"]``.

The registry is keyed by result ``source`` rather than by provider because a
provider mixes engines with different styles (Games merges Apibay,
SolidTorrents, Online-Fix, and FitGirl rows into one table). Adding a
non-standard source means one adapter plus one ``_BY_SOURCE`` line.

Interface:
- ``magnet(result)`` — magnet URI or None; resolves lazily (network) but stays
  silent, callers wrap their own status UI. Drives copy-magnets and batch-aria2.
- ``pick(result)`` — interactive single-pick step. Returns a ``PickOutcome``:
  ``menu`` (magnet ready, proceed to the download-method menu), ``next``
  (acquisition fully handled here), or ``back`` (nothing happened, re-show the
  results table).
- ``batch_item(result, ...)`` — one item of a batch handoff. Returns a
  ``BatchItemOutcome`` the batch loop aggregates into its summary panel.
"""

import threading

import readchar
from rich.markup import escape

from torrent_finder.constants import console
from torrent_finder.utils import build_magnet


class PickOutcome:
    """Result of an interactive single pick.

    ``action`` is ``"menu"`` (proceed to the download-method menu with
    ``magnet``), ``"next"`` (handled here — show "what's next?"), or ``"back"``
    (nothing happened — re-show the results table).
    """

    __slots__ = ("action", "magnet")

    def __init__(self, action: str, magnet: str = "") -> None:
        self.action = action
        self.magnet = magnet


class BatchItemOutcome:
    """Result of one batch-handoff item.

    ``saved_direct`` marks a file saved straight to disk (not a client
    handoff), which the caller excludes from the magnet-dispatch stat.
    ``manual_url`` is a page the user must visit when automation failed (or
    the item can't be batched). ``password`` is surfaced once in the batch
    summary (Online-Fix archive password).
    """

    __slots__ = ("ok", "saved_direct", "manual_url", "password")

    def __init__(self, ok: bool, saved_direct: bool = False,
                 manual_url: str = "", password: str = "") -> None:
        self.ok = ok
        self.saved_direct = saved_direct
        self.manual_url = manual_url
        self.password = password


class MagnetDirect:
    """Result already carries a usable ``info_hash`` — build the magnet."""

    style = "magnet-direct"
    has_magnet = True

    def magnet(self, result) -> str | None:
        info_hash = result.get("info_hash") or ""
        return build_magnet(info_hash, result.get("name", "Unknown")) if info_hash else None

    def client_payload(self, result):
        from torrent_finder.qbittorrent import magnet_payload, ClientError
        magnet = self.magnet(result)
        if not magnet:
            raise ClientError("The source could not resolve a magnet for this result.")
        return magnet_payload(magnet)

    def pick(self, result) -> PickOutcome:
        # Single pick builds the magnet unconditionally (even from an empty
        # hash) — the download-method menu is still useful for its info rows.
        return PickOutcome("menu", build_magnet(result.get("info_hash", ""),
                                                result.get("name", "Unknown")))

    def batch_item(self, result, *, download_dir, cancel_event, set_status) -> BatchItemOutcome:
        magnet = self.magnet(result)
        if not magnet:
            return BatchItemOutcome(ok=False)
        from torrent_finder.downloader import open_magnet
        try:
            open_magnet(magnet)
        except OSError:
            return BatchItemOutcome(ok=False)  # counted with the batch's failures
        return BatchItemOutcome(ok=True)


def _wait_with_esc(message: str, work, *args):
    """Run a lookup under a spinner that Esc cancels; ``(result, cancelled)``.

    A lookup can wait on slow servers (Libgen tries three mirrors, 25 s each),
    and Esc should leave it like it leaves the download itself. A cancelled
    lookup finishes in the background and its result is ignored; *work* gets
    the cancel event as ``cancel_event`` when it accepts one, so it can stop
    early and never write files after a cancel.
    """
    import inspect
    from torrent_finder.utils import start_esc_listener

    cancel = threading.Event()
    box: dict = {}
    kwargs = {"cancel_event": cancel} if "cancel_event" in inspect.signature(work).parameters else {}

    def run() -> None:
        try:
            box["value"] = work(*args, **kwargs)
        except Exception as error:  # re-raised below, in the caller's thread
            box["error"] = error

    worker = threading.Thread(target=run, daemon=True)
    stop_listener = start_esc_listener(cancel)
    try:
        with console.status(f"[bold cyan]{message}[/bold cyan] [dim]Esc to cancel[/dim]", spinner="dots"):
            worker.start()
            while worker.is_alive() and not cancel.is_set():
                worker.join(0.1)
    finally:
        stop_listener.set()
    if worker.is_alive():
        return None, True
    if "error" in box:
        raise box["error"]
    return box.get("value"), False


class MagnetLazyResolve(MagnetDirect):
    """The real hash lives on the topic/post page — resolve on demand.

    Subclasses supply ``_resolve`` (a network call returning the hash or
    None), plus the status/error copy for the interactive pick.
    """

    style = "magnet-lazy-resolve"

    label = ""          # site name for the status line
    error_text = ""     # printed when resolution fails

    def _resolve(self, result) -> str | None:
        raise NotImplementedError

    def magnet(self, result) -> str | None:
        real_hash = self._resolve(result)
        return build_magnet(real_hash, result.get("name", "Unknown")) if real_hash else None

    def pick(self, result) -> PickOutcome:
        real_hash, cancelled = _wait_with_esc(f"Fetching magnet from {self.label}…", self._resolve, result)
        if cancelled:
            return PickOutcome("back")
        if not real_hash:
            console.print(f"[error] {self.error_text}[/error]")
            console.print("[dim]Press any key to continue...[/dim]")
            readchar.readkey()
            return PickOutcome("back")
        # Persist the real hash so everything downstream of the pick (session,
        # info screen, re-picks) sees it instead of the placeholder. The
        # placeholder stays as the listing's identity (see result_identity), so
        # bookmarks and selections still recognise the same listing.
        result.setdefault("listing_hash", result.get("info_hash", ""))
        result["info_hash"] = real_hash
        return PickOutcome("menu", build_magnet(real_hash, result.get("name", "Unknown")))


class RuTrackerAcquisition(MagnetLazyResolve):
    label = "RuTracker"
    error_text = "Couldn't get the magnet from RuTracker (login expired or topic unavailable)."

    def _resolve(self, result) -> str | None:
        from torrent_finder import rutracker
        return rutracker.resolve_info_hash(result.get("rt_topic_id") or result.get("info_hash"))


class FitGirlAcquisition(MagnetLazyResolve):
    label = "FitGirl"
    error_text = "Couldn't get the magnet from FitGirl (post layout changed or site unreachable)."

    def _resolve(self, result) -> str | None:
        from torrent_finder import fitgirl
        return fitgirl.resolve_info_hash(result.get("fg_post_url") or result.get("page_url") or "")


class OnlineFixAcquisition:
    """Online-Fix: no public magnet — fetch the ``.torrent`` and hand it to
    the system torrent client (torrent-file-handoff).

    The post page is public and the file host is referer-gated (no login), so
    the ``.torrent`` is saved into the user's download folder and opened in
    their client. On failure the page URL is shown for a manual grab.
    """

    style = "torrent-file-handoff"
    has_magnet = False

    def magnet(self, result) -> str | None:
        return None

    def client_payload(self, result):
        import tempfile
        from pathlib import Path
        from torrent_finder import online_fix
        from torrent_finder.qbittorrent import torrent_payload, ClientError
        with tempfile.TemporaryDirectory(prefix="torrent-finder-") as directory:
            path = online_fix.fetch_torrent_for(result.get("page_url") or result.get("of_post_url") or "", directory)
            if not path or Path(path).stat().st_size > 8 * 1024 * 1024:
                raise ClientError("Could not obtain Online-Fix torrent metadata. Open its listing manually.")
            return torrent_payload(Path(path).read_bytes())

    def pick(self, result) -> PickOutcome:
        from torrent_finder import online_fix
        from torrent_finder.constants import get_download_dir
        from torrent_finder.downloader import open_torrent_file
        from rich.panel import Panel
        from torrent_finder.ui.prompts import download_dir_ready

        if not download_dir_ready():
            return PickOutcome("back")

        name = result.get("name", "Unknown")
        page_url = result.get("page_url") or result.get("of_post_url") or ""
        path, cancelled = _wait_with_esc("Fetching .torrent from online-fix.me…",
                                         online_fix.fetch_torrent_for, page_url, get_download_dir())
        if cancelled:
            return PickOutcome("back")
        if not path:
            console.print(Panel(
                f"[bold]{escape(name)}[/bold]\n\n"
                "[warning]Couldn't fetch the .torrent automatically[/warning] "
                "(post layout changed or host blocked).\n"
                f"[cyan]Open the page and grab it manually:[/cyan]\n{escape(page_url)}",
                title="🔧 Online-Fix", border_style="yellow", padding=(1, 2),
            ))
            console.print("[dim]Press any key to continue...[/dim]")
            readchar.readkey()
            return PickOutcome("back")

        opened = open_torrent_file(path)
        handoff = ("[success]✓ opened in your torrent client[/success]" if opened
                   else "[warning]saved, but couldn't auto-open — add it to your client manually[/warning]")
        console.print(Panel(
            f"[bold]{escape(name)}[/bold]\n\n"
            f"[cyan].torrent saved:[/cyan]   {escape(path)}\n"
            f"[cyan]Handed to client:[/cyan] {handoff}\n"
            f"[cyan]Archive password:[/cyan] {online_fix.ARCHIVE_PASSWORD}\n\n"
            "[dim]Your client downloads the game from online-fix's tracker; unpack the "
            "archives with the password above.[/dim]",
            title="🔧 Online-Fix", border_style="bright_blue", padding=(1, 2),
        ))
        console.print("[dim]Press any key to continue...[/dim]")
        readchar.readkey()
        return PickOutcome("next")

    def batch_item(self, result, *, download_dir, cancel_event, set_status) -> BatchItemOutcome:
        from torrent_finder import online_fix
        from torrent_finder.downloader import open_torrent_file

        page_url = result.get("page_url") or result.get("of_post_url") or ""
        path = online_fix.fetch_torrent_for(page_url, download_dir)
        if path and open_torrent_file(path):
            return BatchItemOutcome(ok=True, password=online_fix.ARCHIVE_PASSWORD)
        return BatchItemOutcome(ok=False, manual_url=page_url)


class MadokamiAcquisition:
    """Madokami: direct-download library — no magnet, no ``.torrent``.

    A file hit streams straight to the download folder; a directory hit (a
    series) opens as a folder: sub-folders can be browsed into, and files are
    chosen in the file picker. Each checked file then downloads in turn (Esc
    aborts mid-file). Login required.
    """

    style = "direct-download"
    has_magnet = False

    def magnet(self, result) -> str | None:
        return None

    def pick(self, result) -> PickOutcome:
        import os
        from torrent_finder import madokami
        from torrent_finder.constants import get_download_dir
        from torrent_finder.credentials import madokami_config
        from torrent_finder.utils import start_esc_listener
        from rich.panel import Panel

        name = result.get("name", "Unknown")
        path = result.get("mdk_path") or ""
        page_url = result.get("page_url", "")

        if madokami_config() is None:
            console.print(Panel(
                "[warning]Madokami needs a login[/warning] — add your account under "
                "Credentials on the provider screen (or set MADOKAMI_USERNAME / "
                "MADOKAMI_PASSWORD).",
                title="📕 Madokami", border_style="yellow", padding=(1, 2),
            ))
            console.print("[dim]Press any key to continue...[/dim]")
            readchar.readkey()
            return PickOutcome("back")

        if madokami.is_file_path(path):
            dl_paths = [path]
        else:
            dl_paths = self._choose_files(path)
            if not dl_paths:  # Esc / Back out of the picked folder → back to results
                return PickOutcome("back")

        from torrent_finder.ui.prompts import download_dir_ready
        if not download_dir_ready():
            return PickOutcome("back")

        from urllib.parse import unquote
        from rich.progress import (
            BarColumn, DownloadColumn, Progress, TextColumn, TimeRemainingColumn,
            TransferSpeedColumn,
        )

        saved: list[str] = []
        failed: list[str] = []
        cancel_event = threading.Event()
        stop_listener = start_esc_listener(cancel_event)
        # A volume archive can run to hundreds of MB, so show a real transfer bar
        # (size / speed / ETA from Content-Length) instead of a blind spinner, and
        # let Esc abort mid-file (checked per chunk inside download_file).
        # markup=False: manga filenames routinely contain brackets ("[Group] …"),
        # which rich would otherwise try to parse as style tags.
        progress = Progress(
            TextColumn("{task.description}", style="cyan", markup=False),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
        )
        console.print(
            f"[info]Downloading {len(dl_paths)} file(s) from Madokami — press Esc to stop.[/info]"
        )
        try:
            with progress:
                for i, p in enumerate(dl_paths, 1):
                    if cancel_event.is_set():
                        break
                    label = unquote(p.rsplit("/", 1)[-1])
                    if len(label) > 46:
                        label = label[:45] + "…"
                    if len(dl_paths) > 1:
                        label = f"({i}/{len(dl_paths)}) {label}"
                    task = progress.add_task(label, total=None)

                    def _on_progress(done: int, total: int | None, _task=task) -> None:
                        progress.update(_task, completed=done, total=total)

                    dest = madokami.download_file(
                        p, get_download_dir(),
                        cancel_event=cancel_event, progress_cb=_on_progress,
                    )
                    if dest:
                        saved.append(dest)
                    elif not cancel_event.is_set():
                        failed.append(label)
        finally:
            stop_listener.set()

        lines = []
        if cancel_event.is_set():
            lines.append(f"[warning] Stopped after {len(saved)} of {len(dl_paths)}.[/warning]")
        elif saved:
            lines.append(f"[success]✓ {len(saved)} file(s) saved to {escape(get_download_dir())}[/success]")
        for s in saved[:6]:
            lines.append(f"[dim]{escape(os.path.basename(s))}[/dim]")
        if len(saved) > 6:
            lines.append(f"[dim]… +{len(saved) - 6} more[/dim]")
        if failed:
            lines.append(f"[warning] Couldn't download {len(failed)}:[/warning] " + escape(", ".join(failed[:4])))
            lines.append(f"[dim]Grab manually: {escape(page_url)}[/dim]")
        if not lines:
            lines.append("[warning] Nothing downloaded.[/warning]")
        console.print(Panel(
            f"[bold]{escape(name)}[/bold]\n\n" + "\n".join(lines),
            title="📕 Madokami", border_style="bright_blue", padding=(1, 2),
        ))
        console.print("[dim]Press any key to continue...[/dim]")
        readchar.readkey()
        return PickOutcome("next" if saved else "back")

    def _choose_files(self, path) -> list[str]:
        """Browse from a picked folder to the files to download; [] when the user
        backs out of it.

        Series folders often hold only release folders ("!Deluxe Edition
        (Digital)"), so folders open in place. Esc or Back goes up one level, and
        from the picked folder back to the results. Each folder is listed at most
        once per pick: Madokami asks for gentle usage.
        """
        from torrent_finder import madokami
        from torrent_finder.ui.selector import SelectItem, arrow_select

        listings, cursors, trail = {}, {}, []
        current = path
        while True:
            if current not in listings:
                listing, cancelled = _wait_with_esc("Listing the Madokami folder…", madokami.list_directory, current)
                if cancelled:  # Esc: up one level, or back to the results
                    if not trail:
                        return []
                    current = trail.pop()
                    continue
                listings[current] = listing
            children = listings[current]
            here = " › ".join(madokami.describe(current)[0])
            files = [c for c in children or () if not c["is_dir"]]
            folders = [c for c in children or () if c["is_dir"]]
            if children is None or not folders:
                if children is None:
                    del listings[current]  # visiting it again asks again
                    self._notice(here, "[warning]Couldn't list the folder[/warning] (login rejected or "
                                       "site layout changed).", current)
                elif not files:
                    self._notice(here, "[warning]This folder is empty.[/warning]", current)
                else:
                    picked = self._pick_files(files)
                    if picked:
                        return picked
                if not trail:
                    return []
                current = trail.pop()
                continue
            items = []
            if files:
                items.append(SelectItem(f"📄 Choose from the {len(files)} file(s) here", "files",
                                        description="Volumes or chapters stored directly in this folder."))
            items += [SelectItem(f"📁 {folder['name']}", folder["path"], description="Open this folder.")
                      for folder in folders]
            items.append(SelectItem("↩ Back", "back", is_action=True))
            choice = arrow_select(items, title=f"📕 {escape(here)}", start_index=cursors.get(current, 0),
                                  footer="Enter open • Esc back")
            if choice is None or items[choice].value == "back":
                if not trail:
                    return []
                current = trail.pop()
                continue
            cursors[current] = choice
            if items[choice].value == "files":
                picked = self._pick_files(files)
                if picked:
                    return picked
                continue
            trail.append(current)
            current = items[choice].value

    @staticmethod
    def _pick_files(files) -> list[str]:
        """The checked files' paths from the file picker; [] when cancelled."""
        from torrent_finder.torrent_meta import TorrentFile
        from torrent_finder.ui.prompts import episode_select_prompt

        picker_files = [TorrentFile(index=i + 1, name=f["name"], size_bytes=f.get("size", 0))
                        for i, f in enumerate(files)]
        picked = episode_select_prompt(picker_files) or []
        return [files[i - 1]["path"] for i in picked if 1 <= i <= len(files)]

    @staticmethod
    def _notice(here, message, path):
        from torrent_finder import madokami
        from rich.panel import Panel

        console.print(Panel(
            f"[bold]{escape(here)}[/bold]\n\n{message}\n"
            f"[cyan]Open it in your browser instead:[/cyan]\n{escape(madokami._BASE + path)}",
            title="📕 Madokami", border_style="yellow", padding=(1, 2),
        ))
        console.print("[dim]Press any key to continue...[/dim]")
        readchar.readkey()

    def batch_item(self, result, *, download_dir, cancel_event, set_status) -> BatchItemOutcome:
        # Direct download, not a client handoff. Only file hits can be batched
        # — a folder needs its volume picker, so it goes to the manual list.
        from torrent_finder import madokami

        mpath = result.get("mdk_path") or ""
        if not madokami.is_file_path(mpath):
            return BatchItemOutcome(ok=False, manual_url=result.get("page_url") or "")

        # cancel_event makes Esc abort mid-archive, not just between items —
        # these can run to hundreds of MB. The callback keeps a MB counter on
        # the batch status line while the archive streams.
        def _on_progress(done, total):
            size = (f"{done / 1048576:.1f}/{total / 1048576:.1f} MB"
                    if total else f"{done / 1048576:.1f} MB")
            set_status(size)

        if madokami.download_file(
            mpath, download_dir,
            cancel_event=cancel_event, progress_cb=_on_progress,
        ):
            return BatchItemOutcome(ok=True, saved_direct=True)
        return BatchItemOutcome(ok=False, manual_url=result.get("page_url") or "")


class LibgenAcquisition:
    """Libgen: public direct-download library — no magnet, no login.

    A pick resolves the file's keyed download link (mirror failover inside
    ``libgen.resolve_download_url``) and streams it to the download folder
    with a transfer bar; Esc aborts mid-file. On failure the ads page URL is
    shown for a manual grab.
    """

    style = "direct-download"
    has_magnet = False

    def magnet(self, result) -> str | None:
        return None

    def pick(self, result) -> PickOutcome:
        import os
        from torrent_finder import libgen
        from torrent_finder.constants import get_download_dir
        from torrent_finder.utils import start_esc_listener
        from rich.panel import Panel
        from rich.progress import (
            BarColumn, DownloadColumn, Progress, TextColumn, TimeRemainingColumn,
            TransferSpeedColumn,
        )

        name = result.get("name", "Unknown")
        md5 = result.get("lg_md5") or ""
        page_url = result.get("page_url", "")

        from torrent_finder.ui.prompts import download_dir_ready
        if not download_dir_ready():
            return PickOutcome("back")

        url, cancelled = _wait_with_esc("Resolving the download link from Libgen…", libgen.resolve_download_url, md5)
        if cancelled:
            return PickOutcome("back")
        if not url:
            console.print(Panel(
                f"[bold]{escape(name)}[/bold]\n\n"
                "[warning]Couldn't resolve the download link[/warning] "
                "(mirrors unreachable or page layout changed).\n"
                f"[cyan]Open the page and grab it manually:[/cyan]\n{escape(page_url)}",
                title="📖 Libgen", border_style="yellow", padding=(1, 2),
            ))
            console.print("[dim]Press any key to continue...[/dim]")
            readchar.readkey()
            return PickOutcome("back")

        cancel_event = threading.Event()
        stop_listener = start_esc_listener(cancel_event)
        # markup=False: book titles routinely contain brackets, which rich
        # would otherwise try to parse as style tags.
        progress = Progress(
            TextColumn("{task.description}", style="cyan", markup=False),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
        )
        console.print("[info]Downloading from Libgen — press Esc to stop.[/info]")
        ext = result.get("lg_ext") or "bin"
        fallback = f"libgen-{md5[:8]}.{ext}"
        try:
            with progress:
                label = name if len(name) <= 46 else name[:45] + "…"
                task = progress.add_task(label, total=None)

                def _on_progress(done: int, total: int | None) -> None:
                    progress.update(task, completed=done, total=total)

                dest = libgen.download_file(
                    url, get_download_dir(), fallback,
                    cancel_event=cancel_event, progress_cb=_on_progress,
                )
        finally:
            stop_listener.set()

        if dest:
            body = (f"[success]✓ Saved to {escape(get_download_dir())}[/success]\n"
                    f"[dim]{escape(os.path.basename(dest))}[/dim]")
        elif cancel_event.is_set():
            body = "[warning] Download cancelled.[/warning]"
        else:
            body = ("[warning]Download failed.[/warning]\n"
                    f"[cyan]Grab it manually:[/cyan]\n{escape(page_url)}")
        console.print(Panel(
            f"[bold]{escape(name)}[/bold]\n\n{body}",
            title="📖 Libgen", border_style="bright_blue", padding=(1, 2),
        ))
        console.print("[dim]Press any key to continue...[/dim]")
        readchar.readkey()
        return PickOutcome("next" if dest else "back")

    def batch_item(self, result, *, download_dir, cancel_event, set_status) -> BatchItemOutcome:
        # Direct download, not a client handoff (mirrors Madokami's batch path).
        from torrent_finder import libgen

        md5 = result.get("lg_md5") or ""
        url = libgen.resolve_download_url(md5, cancel_event=cancel_event)
        if not url:
            return BatchItemOutcome(ok=False, manual_url=result.get("page_url") or "")

        def _on_progress(done, total):
            size = (f"{done / 1048576:.1f}/{total / 1048576:.1f} MB"
                    if total else f"{done / 1048576:.1f} MB")
            set_status(size)

        ext = result.get("lg_ext") or "bin"
        if libgen.download_file(
            url, download_dir, f"libgen-{md5[:8]}.{ext}",
            cancel_event=cancel_event, progress_cb=_on_progress,
        ):
            return BatchItemOutcome(ok=True, saved_direct=True)
        return BatchItemOutcome(ok=False, manual_url=result.get("page_url") or "")


class FDroidAcquisition:
    """F-Droid: official repository APKs — no magnet, no login.

    A pick resolves the repository's suggested version and downloads that APK
    from f-droid.org with a transfer bar; Esc aborts mid-file. The done panel
    names the package and version, and links F-Droid's PGP signature.
    """

    style = "direct-download"
    has_magnet = False

    def magnet(self, result) -> str | None:
        return None

    def pick(self, result) -> PickOutcome:
        import os
        from torrent_finder import fdroid
        from torrent_finder.constants import get_download_dir
        from torrent_finder.utils import start_esc_listener
        from rich.panel import Panel
        from rich.progress import (
            BarColumn, DownloadColumn, Progress, TextColumn, TimeRemainingColumn,
            TransferSpeedColumn,
        )

        name = result.get("name", "Unknown")
        package = result.get("fd_package") or ""
        page_url = result.get("page_url", "")

        from torrent_finder.ui.prompts import download_dir_ready
        if not download_dir_ready():
            return PickOutcome("back")

        apk, cancelled = _wait_with_esc("Finding the current version on F-Droid…", fdroid.suggested_apk, package)
        if cancelled:
            return PickOutcome("back")
        if not apk:
            console.print(Panel(
                f"[bold]{escape(name)}[/bold]\n\n"
                "[warning]Couldn't find a version to download[/warning] (F-Droid unreachable or no "
                "suggested version).\n"
                f"[cyan]Open the package page instead:[/cyan]\n{escape(page_url)}",
                title="🤖 F-Droid", border_style="yellow", padding=(1, 2),
            ))
            console.print("[dim]Press any key to continue...[/dim]")
            readchar.readkey()
            return PickOutcome("back")
        url, version, builds = apk

        cancel_event = threading.Event()
        stop_listener = start_esc_listener(cancel_event)
        progress = Progress(
            TextColumn("{task.description}", style="cyan", markup=False),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
        )
        console.print("[info]Downloading from F-Droid — press Esc to stop.[/info]")
        try:
            with progress:
                task = progress.add_task(url.rsplit("/", 1)[-1], total=None)

                def _on_progress(done: int, total: int | None) -> None:
                    progress.update(task, completed=done, total=total)

                dest = fdroid.download_apk(url, get_download_dir(), cancel_event=cancel_event,
                                           progress_cb=_on_progress)
        finally:
            stop_listener.set()

        if dest:
            body = (f"[success]✓ Saved to {escape(get_download_dir())}[/success]\n"
                    f"[dim]{escape(os.path.basename(dest))}[/dim]\n\n"
                    f"Package {escape(package)}, version {escape(version or '?')}, from f-droid.org.\n"
                    + (f"[warning]This version has {builds} builds, usually one per CPU type; this is the one "
                       "F-Droid suggests (most phones). For another device type, use the F-Droid app or "
                       f"the package page: {escape(page_url)}[/warning]\n" if builds > 1 else "")
                    +
                    "[dim]Android checks the APK's signature when you install it. "
                    f"F-Droid's PGP signature: {escape(url)}.asc[/dim]")
        elif cancel_event.is_set():
            body = "[warning] Download cancelled.[/warning]"
        else:
            body = ("[warning]Download failed.[/warning]\n"
                    f"[cyan]Get it from the package page:[/cyan]\n{escape(page_url)}")
        console.print(Panel(
            f"[bold]{escape(name)}[/bold]\n\n{body}",
            title="🤖 F-Droid", border_style="bright_blue", padding=(1, 2),
        ))
        console.print("[dim]Press any key to continue...[/dim]")
        readchar.readkey()
        return PickOutcome("next" if dest else "back")

    def batch_item(self, result, *, download_dir, cancel_event, set_status) -> BatchItemOutcome:
        from torrent_finder import fdroid

        apk = fdroid.suggested_apk(result.get("fd_package") or "")
        if not apk:
            return BatchItemOutcome(ok=False, manual_url=result.get("page_url") or "")

        def _on_progress(done, total):
            size = (f"{done / 1048576:.1f}/{total / 1048576:.1f} MB"
                    if total else f"{done / 1048576:.1f} MB")
            set_status(size)

        if fdroid.download_apk(apk[0], download_dir, cancel_event=cancel_event, progress_cb=_on_progress):
            return BatchItemOutcome(ok=True, saved_direct=True)
        return BatchItemOutcome(ok=False, manual_url=result.get("page_url") or "")


# The registry: one line per non-standard source. Anything absent acquires via
# magnet-direct (Apibay, Knaben, SolidTorrents, Nyaa, YTS, …).
_DEFAULT = MagnetDirect()
_BY_SOURCE = {
    "RuTracker": RuTrackerAcquisition(),
    "FitGirl": FitGirlAcquisition(),
    "Online-Fix": OnlineFixAcquisition(),
    "Madokami": MadokamiAcquisition(),
    "Libgen": LibgenAcquisition(),
    "F-Droid": FDroidAcquisition(),
}


def for_result(result):
    """The acquisition adapter for one result, chosen by its ``source``."""
    return _BY_SOURCE.get(result.get("source") or "", _DEFAULT)


def magnet_for(result) -> str | None:
    """Magnet URI for a result, or None when its style has none.

    Lazy-resolve sources hit the network here. Used by batch handoff,
    copy-magnets, and batch-aria2.
    """
    return for_result(result).magnet(result)
