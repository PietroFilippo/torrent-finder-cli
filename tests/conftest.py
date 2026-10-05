"""Shared test setup: run every test in the Simple design unless it chooses another.

Athanor is the app's default design, but most layout tests describe the
Simple design's frames (header line, rules, cursor bar). Tests that start the
app apply its startup appearance, so the baseline is restored around every
test; tests of Athanor apply it themselves.
"""

import pytest

from torrent_finder import paintings
from torrent_finder.ui import appearance, theme

BASELINE = ("quiet", "bar", "comfortable")


def _restore() -> None:
    palette, focus, density = theme.current()
    if (palette.key, focus, density) != BASELINE:
        theme.apply(BASELINE[0], focus=BASELINE[1], density=BASELINE[2])
    appearance._session["painting"] = paintings.DEFAULT


_restore()


@pytest.fixture(autouse=True)
def simple_design():
    _restore()
    yield
    _restore()
