"""Optional client connection, explicit handoff, and refreshable real progress."""

from datetime import datetime
import threading

from rich.markup import escape

from torrent_finder import acquisition
from torrent_finder.constants import console
from torrent_finder.qbittorrent import Client, ClientError, configured
from torrent_finder.ui.creator import _notice, _run_cancellable
from torrent_finder.ui.prompts import get_query_with_shortcut
from torrent_finder.ui.selector import SelectItem, arrow_select
from torrent_finder.ui.search_diagnostics import read_details
from torrent_finder.utils import format_size, start_esc_listener


def _read(fn, message):
    cancelled, result = _run_cancellable(fn, message)
    if cancelled:
        return None
    if isinstance(result, ClientError) or result is None:
        _notice(str(result) if result else "Could not read qBittorrent state.")
        return None
    return result


def progress_text(row):
    progress = min(1.0, max(0.0, float(row.get("progress") or 0)))
    eta = int(row.get("eta") or 0)
    eta_text = f"{eta // 60}m {eta % 60}s" if 0 < eta < 8640000 else "unknown"
    return (f"{row.get('name', 'Unnamed')}\n"
            f"Progress: {progress:.1%} • Client state: {row.get('state', 'unknown')}\n"
            f"Downloaded: {format_size(int(row.get('downloaded') or 0))} • "
            f"Speed: {format_size(int(row.get('dlspeed') or 0))}/s • ETA: {eta_text}\n"
            f"Save folder: {row.get('save_path', '')}\nCategory: {row.get('category', '') or '(none)'}")


def show_progress(client, hashes=()):
    while True:
        rows = _read(lambda: client.torrents(hashes), "Reading qBittorrent progress…")
        if rows is None:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        items = [SelectItem(str(r.get("name", "Unnamed")), value=r,
                            hint=f"{float(r.get('progress') or 0):.1%} · {r.get('state', 'unknown')}",
                            description=escape(progress_text(r))) for r in rows]
        if not rows:
            items.append(SelectItem("No torrents reported by the client", passive=True))
        items += [SelectItem("🔄 Refresh progress", value="refresh"), SelectItem("↩ Back", value=None)]
        while True:
            index = arrow_select(items, title=f"qBittorrent · read at {stamp}",
                                 footer="Enter details • R refresh • Esc back",
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
            read_details(progress_text(value), "Client progress")


def client_menu():
    from torrent_finder.credential_registry import get_credential_spec
    from torrent_finder.ui.credentials import _manage_credentials
    while True:
        items = [SelectItem("⚙ Configure / verify WebUI connection", "setup"),
                 SelectItem("📊 Download progress in qBittorrent", "progress", enabled=configured()),
                 SelectItem("↩ Back", None)]
        index = arrow_select(items, title="qBittorrent", footer="Optional WebUI integration • Esc back")
        if index is None or items[index].value is None:
            return
        if items[index].value == "setup":
            _manage_credentials(get_credential_spec("qbittorrent"))
            continue
        client = None
        try:
            client = Client.from_settings()
            if _read(client.connect, "Connecting to qBittorrent…") is not None:
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
        _notice("These results are direct downloads, not torrents. Use their existing download option.")
        return False
    client = None
    try:
        client = Client.from_settings()
        if _read(client.connect, "Connecting to qBittorrent…") is None:
            return False
        categories = _read(client.categories, "Reading client categories…")
        if categories is None:
            return False
        save_path, category = "", ""
        while True:
            items = [SelectItem("📁 Save folder on client", "folder", description=escape(save_path or "qBittorrent default folder")),
                     SelectItem("🏷 Category", "category", description=escape(category or "No category")),
                     SelectItem(f"🧲 Send {len(eligible)} torrent(s) to qBittorrent", "send",
                                description=f"Full torrents; file selection is managed in qBittorrent. {skipped} direct-download result(s) skipped."),
                     SelectItem("↩ Back", None)]
            index = arrow_select(items, title="Send to qBittorrent", footer="Choose destination, then Send • Esc back")
            if index is None or items[index].value is None:
                return False
            action = items[index].value
            if action == "folder":
                value = get_query_with_shortcut("Client folder (blank = default): ", initial=save_path)
                if isinstance(value, str) and value != "GO_BACK":
                    save_path = value.strip()
            elif action == "category":
                choices = [SelectItem("No category", "")] + [SelectItem(name, name) for name in sorted(categories)]
                pick = arrow_select(choices, title="qBittorrent category", footer="Existing client categories • Esc back")
                if pick is not None:
                    category = choices[pick].value
            else:
                break
        cancel = threading.Event()
        stop = start_esc_listener(cancel)
        lines, hashes = [], []
        try:
            with console.status("Sending to qBittorrent… Esc stops after the current request"):
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
                        status = "already selected" if payload.info_hash in hashes else client.add(payload, save_path, category)
                        hashes.append(payload.info_hash)
                        lines.append(f"{row.get('name', 'Unnamed')}: {status}")
                    except ClientError as error:
                        lines.append(f"{row.get('name', 'Unnamed')}: {error}")
                    except Exception:
                        lines.append(f"{row.get('name', 'Unnamed')}: source could not prepare this torrent.")
        finally:
            stop.set()
        if cancel.is_set():
            lines.append("Stopped. Torrents already submitted remain in the client.")
        if skipped:
            lines.append(f"Skipped {skipped} direct downloads.")
        if any(r.get("source") == "Online-Fix" for r in eligible):
            from torrent_finder.online_fix import ARCHIVE_PASSWORD
            lines.append("Online-Fix archive password: " + ARCHIVE_PASSWORD)
        read_details("\n".join(lines) or "Nothing submitted.", "qBittorrent handoff")
        if hashes:
            show_progress(client, tuple(dict.fromkeys(hashes)))
        return bool(hashes)
    except ClientError as error:
        _notice(str(error))
        return False
    finally:
        if client:
            client.close()
