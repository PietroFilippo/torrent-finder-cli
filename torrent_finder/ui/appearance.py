"""Appearance: the theme, focus style and density, saved per machine.

At startup the theme comes from ``--theme`` (this run only), then the
``TORRENT_FINDER_THEME`` environment variable, then the saved setting, then
Quiet Blue. Focus style and density come from the saved setting. The
Settings › Appearance screen previews a theme in place and saves the choice.
See docs/adr/0021-themes.md.
"""

from __future__ import annotations

import os

from torrent_finder.ui import theme

SETTING = "appearance"
ENV = "TORRENT_FINDER_THEME"
DEFAULTS = {"theme": theme.DEFAULT_THEME, "focus": "bar", "density": "comfortable"}


def theme_key(name: object) -> str | None:
    """The registered theme a user-typed *name* means: a key or a display name, any case or spacing."""
    if not isinstance(name, str):
        return None
    folded = "".join(name.split()).casefold().replace("-", "").replace("_", "")
    for key, palette in theme.THEMES.items():
        if folded in (key, "".join(palette.name.split()).casefold()):
            return key
    return None


def normalize(value: object) -> dict:
    """A complete, valid appearance dict; anything unknown falls back to its default."""
    value = value if isinstance(value, dict) else {}
    return {
        "theme": theme_key(value.get("theme")) or DEFAULTS["theme"],
        "focus": value.get("focus") if value.get("focus") in theme.FOCUS_STYLES else DEFAULTS["focus"],
        "density": value.get("density") if value.get("density") in theme.DENSITIES else DEFAULTS["density"],
    }


def saved() -> dict:
    """The saved appearance, or the defaults when nothing (valid) is saved or settings are unreadable."""
    try:
        from torrent_finder.state import load_setting
        return normalize(load_setting(SETTING, None))
    except Exception:  # an unreadable store must never stop the app from drawing
        return dict(DEFAULTS)


def env_theme(environ=None) -> tuple[str | None, str]:
    """The theme the environment asks for, and a notice when its value names no theme."""
    raw = (os.environ if environ is None else environ).get(ENV, "")
    if not raw.strip():
        return None, ""
    key = theme_key(raw)
    if key is None:
        names = ", ".join(theme.THEMES)
        return None, f"{ENV}={raw.strip()} is not a theme ({names}); using the saved theme."
    return key, ""


def resolve(cli_theme: str | None = None, environ=None) -> tuple[dict, str, str]:
    """The appearance to start with, where its theme came from, and any notice.

    The source is ``"cli"``, ``"env"`` or ``"saved"``.
    """
    appearance = saved()
    key, notice = env_theme(environ)
    source = "saved"
    if key:
        appearance["theme"], source = key, "env"
    cli_key = theme_key(cli_theme) if cli_theme else None
    if cli_key:
        appearance["theme"], source = cli_key, "cli"
    return appearance, source, notice


_session = {"source": "saved"}


def apply_startup(cli_theme: str | None = None, environ=None) -> str:
    """Apply the startup appearance; returns a notice for the first screen ("" when none)."""
    appearance, source, notice = resolve(cli_theme, environ)
    _session["source"] = source
    theme.apply(appearance["theme"], focus=appearance["focus"], density=appearance["density"])
    return notice


def override_source() -> str:
    """``"cli"`` or ``"env"`` when this run's theme overrides the saved one, else ``"saved"``."""
    return _session["source"]


def save(theme_name: str, focus: str, density: str) -> None:
    """Save an explicit appearance choice now; raises ``ValueError``/``OSError`` when that fails."""
    from torrent_finder.state import commit_setting
    commit_setting(SETTING, normalize({"theme": theme_name, "focus": focus, "density": density}))
    _session["source"] = "saved"
