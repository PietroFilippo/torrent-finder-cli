"""Offline appearance captures, including every selectable row and profile confirmations.

python tests/capture_i18n_appearance.py ui-appearance-owned-pt pt-BR
python scripts/ui_snapshots.py check ui-appearance-owned-pt
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import isolation  # noqa: F401
from scripts import ui_snapshots as snapshots
from test_i18n_appearance import menu_fixture
from torrent_finder.ui import prompts, selector


def scenarios():
    cases = []
    for palette, installed, look in [("citrinitas", False, "full"), ("citrinitas", True, "full"),
                                      ("citrinitas", True, "plain"), ("quiet", True, "full")]:
        options = dict(palette=palette, installed=installed, look=look)
        with menu_fixture(**options) as menu:
            rows = [(index, row.value) for index, row in enumerate(menu["items"]) if row.enabled]
        for index, value in rows:
            def draw(index=index, options=options):
                with menu_fixture(**options) as menu:
                    selector.console.print(selector._build_panel(
                        menu["items"], index, menu["title"], False, menu["footer"](), status=menu["status"]()))
            cases.append((f"appearance-{palette}-{installed}-{look}-{index}", draw))

    for look in ("full", "plain"):
        def confirm(look=look):
            def choose(items, kwargs):
                index = next(i for i, row in enumerate(items) if row.value == ("profile", "add"))
                kwargs["on_action"](index, items)
            with menu_fixture(look=look, action=choose) as menu:
                args, kwargs = menu["confirm"].call_args
            prompts.confirm_prompt(*args, **kwargs)
        cases.append((f"appearance-confirm-{look}", confirm))
    return cases


if __name__ == "__main__":
    with patch.object(snapshots, "_scenarios", scenarios), \
         patch.object(snapshots, "SIZES", [(40, 12), (80, 24), (137, 36), (200, 50)]):
        snapshots.capture(sys.argv[1], "citrinitas:lang=" + sys.argv[2])
