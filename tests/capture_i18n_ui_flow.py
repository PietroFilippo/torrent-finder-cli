"""Supplement the standard snapshots with main.py's translated flow messages.

    python tests/capture_i18n_ui_flow.py ui-flow-main-pt pt-BR
    python scripts/ui_snapshots.py check ui-flow-main-pt
"""

import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import isolation  # noqa: E402,F401
import ui_snapshots as snapshots  # noqa: E402
from torrent_finder import acquisition, main  # noqa: E402
from torrent_finder.providers.movie_provider import MovieProvider  # noqa: E402
from torrent_finder.ui import chrome  # noqa: E402

standard_scenarios = snapshots._scenarios


def batch_summary():
    row = {"name": "Fixture [2026]", "info_hash": "a" * 40}
    outcome = acquisition.BatchItemOutcome(True)
    adapter = SimpleNamespace(has_magnet=True, batch_item=lambda *_a, **_k: outcome)
    with patch.object(acquisition, "for_result", return_value=adapter), \
         patch.object(acquisition, "batch_download_dir", return_value=""), \
         patch.object(main, "start_esc_listener", return_value=threading.Event()), \
         patch.object(main.console, "status", return_value=MagicMock()), \
         patch.object(main, "record_torrent_picked"), patch.object(main, "record_magnet_dispatch"):
        main._batch_handoff_run(MovieProvider(), [row], [0])


def saved_error():
    def fail():
        raise OSError("Fixture error")
    main._saved_data_action(fail)


def result_summary():
    provider = MovieProvider()
    provider.active_presets = [next(p for p in provider.presets if p.name == "With Subtitles")]
    main.browse_results(provider, snapshots._sample_results())


def scenarios():
    chrome.clear_messages()
    return standard_scenarios() + [("flow-batch-summary", batch_summary), ("flow-saved-error", saved_error),
            ("flow-result-summary", result_summary), ("flow-goodbye", main._goodbye)]


if __name__ == "__main__":
    snapshots.SIZES = [(40, 12), (80, 24), (137, 36), (200, 50)]
    snapshots._scenarios = scenarios
    snapshots.capture(sys.argv[1], "citrinitas:lang=" + sys.argv[2])
