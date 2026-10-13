"""Optional client connection, explicit handoff, and refreshable real progress."""

# i18n: converted

from datetime import datetime
import threading

from rich.markup import escape

from torrent_finder import acquisition
from torrent_finder.constants import console
from torrent_finder.i18n import t, tn
from torrent_finder.qbittorrent import Client, ClientError, configured
from torrent_finder.ui.creator import _notice, _run_cancellable
from torrent_finder.ui.prompts import PROMPT, get_query_with_shortcut, input_screen
from torrent_finder.ui.selector import SelectItem, arrow_select
from torrent_finder.ui.search_diagnostics import read_details
from torrent_finder.utils import format_size, start_esc_listener


def _read(fn, message):
    cancelled, result = _run_cancellable(fn, message)
    if cancelled:
        return None
    if isinstance(result, ClientError) or result is None:
        _notice(str(result) if result else t("Could not read qBittorrent state."))
        return None
    return result


def _name(row) -> str:
    return str(row["name"]) if "name" in row else t("Unnamed")


def _state(row) -> str:
    """The client's own state word (``downloading``, ``stalledDL``), as qBittorrent reports it."""
    return str(row["state"]) if "state" in row else t("unknown")


def progress_text(row):
    progress = min(1.0, max(0.0, float(row.get("progress") or 0)))
    eta = int(row.get("eta") or 0)
    eta_text = f"{eta // 60}m {eta % 60}s" if 0 < eta < 8640000 else t("unknown")
    return "\n".join([
        _name(row),
        t("Progress: {progress} • Client state: {state}", progress=f"{progress:.1%}", state=_state(row)),
        t("Downloaded: {downloaded} • Speed: {speed}/s • ETA: {eta}",
          downloaded=format_size(int(row.get("downloaded") or 0)), speed=format_size(int(row.get("dlspeed") or 0)),
          eta=eta_text),
        t("Save folder: {folder}", folder=row.get("save_path", "")),
        t("Category: {category}", category=row.get("category", "") or t("(none)")),
    ])


def show_progress(client, hashes=()):
    while True:
        rows = _read(lambda: client.torrents(hashes), t("Reading qBittorrent progress…"))
        if rows is None:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        items = [SelectItem(_name(r), value=r,
                            hint=f"{float(r.get('progress') or 0):.1%} · {_state(r)}",
                            description=escape(progress_text(r))) for r in rows]
        if not rows:
            items.append(SelectItem(t("No torrents reported by the client"), passive=True))
        items += [SelectItem(t("Refresh progress"), value="refresh", hint="R"), SelectItem(t("Back"), value=None)]
        while True:
            index = arrow_select(items, title=t("qBittorrent progress"), status=t("read at {time}", time=stamp),
                                 footer=t("Enter details • R refresh • Esc back"),
                                 hotkeys={"r": "refresh", "R": "refresh"})
            if index is None:
                return
            if isinstance(index, tuple):
                break
            value = items[index].value
            if value is None:
                return
            if value == "refresh":
                break
            read_details(progress_text(value), t("Client progress"))


def client_menu():
    from torrent_finder.credential_registry import get_credential_spec
    from torrent_finder.ui.credentials import _manage_credentials
    while True:
        items = [SelectItem(t("Configure / verify WebUI connection"), "setup"),
                 SelectItem(t("Download progress in qBittorrent"), "progress", enabled=configured()),
                 SelectItem(t("Back"), None)]
        index = arrow_select(items, title="qBittorrent",  # i18n: ignore (proper name)
                             footer=t("Optional WebUI integration • Esc back"))
        if index is None or items[index].value is None:
            return
        if items[index].value == "setup":
            _manage_credentials(get_credential_spec("qbittorrent"))
            continue
        client = None
        try:
            client = Client.from_settings()
            if _read(client.connect, t("Connecting to qBittorrent…")) is not None:
                show_progress(client)
        except ClientError as error:
            _notice(str(error))
        finally:
            if client:
                client.close()


def send_results(results, *, magnet=None):
    eligible = [r for r in results if hasattr(acquisition.for_result(r), "client_payload")]
    skipped = len(results) - len(eligible)
    if not eligible:
        _notice(t("These results are direct downloads, not torrents. Use their existing download option."))
        return False
    client = None
    try:
        client = Client.from_settings()
        if _read(client.connect, t("Connecting to qBittorrent…")) is None:
            return False
        categories = _read(client.categories, t("Reading client categories…"))
        if categories is None:
            return False
        save_path, category = "", ""
        while True:
            # English keeps its "(s)"; a translation gives a singular and a plural.
            sent = tn("Send {n} torrent(s) to qBittorrent", "Send {n} torrent(s) to qBittorrent", len(eligible))
            about = " ".join((t("Full torrents; file selection is managed in qBittorrent."),
                              tn("{n} direct-download result(s) skipped.", "{n} direct-download result(s) skipped.",
                                 skipped)))
            items = [SelectItem(t("Save folder on client"), "folder",
                                description=escape(save_path or t("qBittorrent default folder"))),
                     SelectItem(t("Category"), "category", description=escape(category or t("No category"))),
                     SelectItem(sent, "send", description=about),
                     SelectItem(t("Back"), None)]
            index = arrow_select(items, title=t("Send to qBittorrent"),
                                 footer=t("Choose destination, then Send • Esc back"))
            if index is None or items[index].value is None:
                return False
            action = items[index].value
            if action == "folder":
                value = get_query_with_shortcut(PROMPT, initial=save_path, screen_renderer=input_screen(
                    t("Client folder"), t("Blank uses qBittorrent's default folder.")))
                if isinstance(value, str) and value != "GO_BACK":
                    save_path = value.strip()
            elif action == "category":
                choices = [SelectItem(t("No category"), "")] + [SelectItem(name, name) for name in sorted(categories)]
                pick = arrow_select(choices, title=t("qBittorrent category"),
                                    footer=t("Existing client categories • Esc back"))
                if pick is not None:
                    category = choices[pick].value
            else:
                break
        cancel = threading.Event()
        stop = start_esc_listener(cancel)
        lines, hashes = [], []
        try:
            with console.status(t("Sending to qBittorrent… Esc stops after the current request")):
                for row in eligible:
                    if cancel.is_set():
                        break
                    try:
                        if magnet and len(eligible) == 1:
                            from torrent_finder.qbittorrent import magnet_payload
                            payload = magnet_payload(magnet)
                        else:
                            payload = acquisition.for_result(row).client_payload(row)
                        if cancel.is_set():
                            break
                        if payload.info_hash in hashes:
                            status = t("already selected")
                        else:
                            status = client.add(payload, save_path, category)
                            status = t(status)
                        hashes.append(payload.info_hash)
                        lines.append(f"{_name(row)}: {status}")
                    except ClientError as error:
                        lines.append(f"{_name(row)}: {error}")
                    except Exception:
                        lines.append(t("{name}: source could not prepare this torrent.", name=_name(row)))
        finally:
            stop.set()
        if cancel.is_set():
            lines.append(t("Stopped. Torrents already submitted remain in the client."))
        if skipped:
            # English keeps its plural; a translation gives a singular and a plural.
            lines.append(tn("Skipped {n} direct downloads.", "Skipped {n} direct downloads.", skipped))
        if any(r.get("source") == "Online-Fix" for r in eligible):
            from torrent_finder.online_fix import ARCHIVE_PASSWORD
            lines.append(t("Online-Fix archive password: {password}", password=ARCHIVE_PASSWORD))
        read_details("\n".join(lines) or t("Nothing submitted."), t("qBittorrent handoff"))
        if hashes:
            show_progress(client, tuple(dict.fromkeys(hashes)))
        return bool(hashes)
    except ClientError as error:
        _notice(str(error))
        return False
    finally:
        if client:
            client.close()
