"""User-facing prompts: banner, download method selection."""

import sys

import readchar
from rich.panel import Panel
from rich.text import Text

from constants import console
from downloader import (
    detect_torrent_client,
    download_with_webtorrent,
    has_webtorrent,
    has_peerflix,
    open_magnet,
)
from providers import PROVIDERS
from ui.selector import SelectItem, arrow_select


def get_query_with_shortcut(prompt_str: str) -> str | None:
    """Get input from user manually, returning 'SPECIAL_FILTER' instantly if they press Shift+F as first char."""
    console.print(prompt_str, end="")
    sys.stdout.flush()
    
    buffer = []
    while True:
        key = readchar.readkey()
        
        if not buffer and key == "F":
            print()
            return "SPECIAL_FILTER"
            
        if key in (readchar.key.ENTER, readchar.key.CR, readchar.key.LF):
            print()
            return "".join(buffer)
            
        elif key == readchar.key.ESC:
            print()
            return "GO_BACK"
            
        elif key in (readchar.key.BACKSPACE, '\x08', '\x7f'):
            if buffer:
                buffer.pop()
                sys.stdout.write('\b \b')
                sys.stdout.flush()
                
        elif key in (readchar.key.CTRL_C, '\x03'):
            raise KeyboardInterrupt
            
        elif key in (readchar.key.CTRL_D, '\x04'):
            raise EOFError
            
        elif len(key) == 1 and not key.startswith('\x1b') and not key.startswith('\x00') and not key.startswith('\xe0'):
            buffer.append(key)
            sys.stdout.write(key)
            sys.stdout.flush()


def filter_menu(provider) -> None:
    """Show engine toggles and filter presets in a single menu."""
    has_engines = hasattr(provider, 'engines') and provider.engines
    has_presets = bool(provider.presets)

    if not has_engines and not has_presets:
        console.print("[warning] No filters available for this provider.[/warning]")
        return

    items = []

    # --- Section 1: Search Engines ---
    engine_indices = []
    if has_engines:
        items.append(SelectItem(
            label="─── Search Engines ───",
            value="section_header",
            enabled=False,
            is_action=True,
        ))
        for engine in provider.engines:
            items.append(SelectItem(
                label=f"{engine.icon} {engine.name}",
                value=("engine", engine),
                toggled=engine.enabled,
            ))
            engine_indices.append(len(items) - 1)

    # --- Section 2: Filter Presets ---
    preset_indices = []
    if has_presets:
        items.append(SelectItem(
            label="─── Filter Presets ───",
            value="section_header",
            enabled=False,
            is_action=True,
        ))
        for p in provider.presets:
            items.append(SelectItem(
                label=p.name,
                value=("preset", p),
                toggled=p in provider.active_presets,
            ))
            preset_indices.append(len(items) - 1)

    # --- Action buttons ---
    items.append(SelectItem(label="Clear filters", value="clear", is_action=True))
    items.append(SelectItem(label="✅ Confirm", value="confirm", is_action=True))
    items.append(SelectItem(label="↩ Go Back", value="back", is_action=True))

    def handle_filter_action(idx, items):
        if items[idx].value == "clear":
            # Clear preset toggles only — leave engine toggles alone
            for pi in preset_indices:
                items[pi].toggled = False
            return True  # Stay in menu
        return False  # Exit for Confirm / Go Back

    # Start cursor on first enabled item (skip header)
    start = 1 if has_engines else 0

    result_idx = arrow_select(
        items,
        title=f"Filters — {provider.label}",
        multi=True,
        banner=_make_banner_panel(),
        on_action=handle_filter_action,
        start_index=start,
    )

    if result_idx is None:
        return

    action = items[result_idx].value

    if action == "confirm":
        # Apply engine toggles
        for idx in engine_indices:
            item = items[idx]
            _type, engine = item.value
            engine.enabled = item.toggled

        # Apply preset toggles
        provider.active_presets.clear()
        for idx in preset_indices:
            item = items[idx]
            if item.toggled:
                _type, preset = item.value
                provider.active_presets.append(preset)

        from state import save_state
        save_state(PROVIDERS)
    # "back" — just return


def _make_banner_panel() -> Panel:
    """Return the app banner as a Rich Panel renderable."""
    banner = Text()
    banner.append("Torrent Search CLI", style="bold magenta")
    return Panel(
        banner,
        border_style="bright_blue",
        padding=(1, 2),
    )


def print_banner() -> None:
    """Display the app banner."""
    console.print(_make_banner_panel())
    console.print()


import os

def clear_screen() -> None:
    """Clear the console and reprint the banner to reduce visual pollution."""
    os.system('cls' if os.name == 'nt' else 'clear')
    print_banner()


def download_method_prompt(magnet: str = "", show_subtitles: bool = True) -> str | None:
    """
    Prompt the user to choose a download method.
    Returns 't', 'd', 's', 'back', or None.
    'l' (copy magnet) is handled internally.
    """
    wt_available = has_webtorrent()
    pf_available = has_peerflix()
    client_name = detect_torrent_client()

    items = [
        SelectItem(
            label=f"Open in {client_name}",
            value="t",
        ),
        SelectItem(
            label="Stream to VLC (peerflix)",
            value="stream_p",
            enabled=pf_available,
            hint="Requires VLC installed" if pf_available else "(not installed)",
        ),
        SelectItem(
            label="Stream to VLC (webtorrent)",
            value="stream_w",
            enabled=wt_available,
            hint="Requires VLC installed" if wt_available else "(not installed)",
        ),
        SelectItem(
            label="Download directly (peerflix)",
            value="p",
            enabled=pf_available,
            hint="Slower, won't seed" if pf_available else "(not installed)",
        ),
        SelectItem(
            label="Download directly (webtorrent)",
            value="d",
            enabled=wt_available,
            hint="Slower, won't seed" if wt_available else "(not installed)",
        ),
    ]

    if show_subtitles:
        items.append(SelectItem(
            label="Search & Download Subtitles",
            value="s",
        ))

    items.append(SelectItem(
        label="Copy magnet link",
        value="l",
        is_action=True,
    ))

    items.append(SelectItem(label="↩ Go back to results", value="back"))
    items.append(SelectItem(label="Cancel", value=None))

    def handle_download_action(idx, items):
        if items[idx].value == "l" and magnet:
            try:
                import subprocess, platform
                if platform.system() == "Windows":
                    subprocess.run("clip", input=magnet.encode(), check=True)
                elif platform.system() == "Darwin":
                    subprocess.run("pbcopy", input=magnet.encode(), check=True)
                else:
                    subprocess.run(["xclip", "-selection", "clipboard"], input=magnet.encode(), check=True)
                items[idx].hint = "✅ Copied!"
            except Exception:
                items[idx].hint = "⚠ Could not copy"
            return True  # Stay in menu
        return False

    idx = arrow_select(
        items,
        title="Download Method",
        banner=_make_banner_panel(),
        on_action=handle_download_action,
    )

    if idx is None:
        return None

    return items[idx].value


def provider_select_prompt() -> object | None:
    """Prompt the user to select a torrent provider. Returns the provider object or None if cancelled."""
    items = [SelectItem(label=p.label, value=p) for p in PROVIDERS]

    idx = arrow_select(
        items,
        title="Select Provider",
        footer="↑/↓ navigate  •  Enter select  •  Esc cancel\n   Tip: For the best results, search using the complete name.",
        banner=_make_banner_panel(),
    )

    if idx is None:
        return None

    return items[idx].value


def search_again_prompt() -> str | None:
    """Prompt the user for what to do next after a download.

    Returns 'search', 'provider', or None (exit).
    """
    items = [
        SelectItem(label="🔍 Search Again", value="search"),
        SelectItem(label="🔄 Change Provider", value="provider"),
        SelectItem(label="👋 Exit", value="exit"),
    ]

    idx = arrow_select(
        items,
        title="What's Next?",
        banner=_make_banner_panel(),
    )

    if idx is None:
        return None

    return items[idx].value
