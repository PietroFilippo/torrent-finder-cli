"""Extra isolated captures for the credentials batch's forms and WebUI screens.

    python tests/credentials_i18n_snapshots.py credentials-details-pt pt-BR
    python tests/credentials_i18n_snapshots.py credentials-details-qps qps

Uses the shared snapshot sizes and overflow checker; no real credentials or network.
"""

import sys
import threading
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import isolation  # noqa: E402,F401
from scripts import ui_snapshots as snapshots  # noqa: E402
from torrent_finder import credentials, qbittorrent  # noqa: E402
from torrent_finder.credential_registry import get_credential_spec  # noqa: E402
from torrent_finder.ui import credentials as ui  # noqa: E402
from torrent_finder.ui import qbittorrent as client_ui  # noqa: E402


def scenarios():
    def form(credential_id):
        def run():
            with patch.object(credentials, "get_credential", return_value=None), \
                 patch.object(credentials, "env_overrides", return_value=False):
                ui._credentials_form(get_credential_spec(credential_id), {})
        return run

    def stored():
        with patch.object(credentials, "get_credential", return_value="test-only-value"), \
             patch.object(credentials, "credential_source", return_value="file"):
            ui._view_credentials(get_credential_spec("opensubtitles"))

    def manage():
        with patch.object(credentials, "get_credential", return_value=None), \
             patch.object(credentials, "file_has", return_value=False), \
             patch.object(credentials, "env_overrides", return_value=False):
            ui._manage_credentials(get_credential_spec("qbittorrent"))

    def menu():
        with patch.object(client_ui, "configured", return_value=True):
            client_ui.client_menu()

    def progress(empty=False):
        client = Mock()
        client.torrents.return_value = [] if empty else [{
            "name": "Example torrent", "progress": 0.42, "state": "downloading", "downloaded": 420_000_000,
            "dlspeed": 1_200_000, "eta": 130, "save_path": "/downloads", "category": "movies"}]
        with patch.object(client_ui, "_read", side_effect=lambda fn, message: fn()):
            client_ui.show_progress(client)

    def handoff(action=None):
        client = Mock()
        client.connect.return_value = "5.1.0"
        client.categories.return_value = {"movies": {}}
        client.torrents.return_value = []
        client.add.return_value = "added to client"
        acquisition = Mock()
        acquisition.client_payload.return_value = qbittorrent.TorrentPayload("a" * 40)
        select = client_ui.arrow_select
        first = True

        def choose(items, **kwargs):
            nonlocal first
            if first and action is not None:
                first = False
                return action
            return select(items, **kwargs)

        with patch.object(client_ui.Client, "from_settings", return_value=client), \
             patch.object(client_ui, "_read", side_effect=lambda fn, message: fn()), \
             patch.object(client_ui, "arrow_select", side_effect=choose), \
             patch.object(client_ui.acquisition, "for_result", return_value=acquisition), \
             patch.object(client_ui, "start_esc_listener", return_value=threading.Event()):
            client_ui.send_results([{"source": "Nyaa", "info_hash": "a" * 40}])

    return [(f"credentials-form-{name}", form(name)) for name in ("qbittorrent", "tmdb", "igdb")] + [
        ("credentials-stored", stored), ("credentials-manage", manage), ("qbittorrent-menu", menu),
        ("qbittorrent-progress", progress), ("qbittorrent-empty", lambda: progress(True)),
        ("qbittorrent-send", handoff), ("qbittorrent-folder", lambda: handoff(0)),
        ("qbittorrent-category", lambda: handoff(1)), ("qbittorrent-handoff", lambda: handoff(2))]


if __name__ == "__main__":
    snapshots._scenarios = scenarios
    snapshots.capture(sys.argv[1], "citrinitas:lang=" + sys.argv[2])
    raise SystemExit(bool(snapshots.check(sys.argv[1])))
