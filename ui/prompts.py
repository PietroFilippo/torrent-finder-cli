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
    """Show the currently available presets and allow toggling them."""
    if not provider.presets:
        console.print("[warning] No presets available for this provider.[/warning]")
        return

    # Build toggle items: first item is "Clear all filters", rest are presets
    items = [SelectItem(label="Clear all filters", value="clear")]
    for p in provider.presets:
        items.append(SelectItem(
            label=p.name,
            value=p,
            toggled=p in provider.active_presets,
        ))

    result = arrow_select(
        items,
        title=f"Filter Presets — {provider.label}",
        multi=True,
        footer="↑/↓ navigate  •  Space toggle  •  Enter confirm  •  Esc cancel",
        banner=_make_banner_panel(),
    )

    if result is None:
        return

    # Check if "Clear all" was toggled
    if 0 in result:
        provider.active_presets.clear()
        console.print("[success] All filters cleared.[/success]")
        return

    # Apply toggled presets
    provider.active_presets.clear()
    for idx in result:
        preset = items[idx].value
        provider.active_presets.append(preset)

    active_names = [p.name for p in provider.active_presets]
    if active_names:
        console.print(f"[success] Active filters: {', '.join(active_names)}[/success]")
    else:
        console.print("[success] All filters cleared.[/success]")


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


def download_method_prompt(show_subtitles: bool = True) -> str | None:
    """
    Prompt the user to choose a download method.
    Returns 't' for torrent client, 'd' for direct download, 's' for subtitles, None for cancel.
    """
    wt_available = has_webtorrent()
    client_name = detect_torrent_client()

    items = [
        SelectItem(
            label=f"Open in {client_name}",
            value="t",
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
    ))

    items.append(SelectItem(label="Cancel", value=None))

    idx = arrow_select(items, title="Download Method", banner=_make_banner_panel())

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
