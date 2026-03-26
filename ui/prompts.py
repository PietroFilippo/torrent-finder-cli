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
        
    while True:
        clear_screen()
        console.print(f"\n[title]Filter Presets for {provider.label}:[/title]")
        options = ["[0] Clear all filters"]
        for i, p in enumerate(provider.presets, 1):
            is_active = p in provider.active_presets
            prefix = "[bold green]✓[/bold green]" if is_active else "[dim] [/dim]"
            options.append(f"{prefix} [{i}] {p.name}")
            
        for opt in options:
            console.print(f"  {opt}")
        console.print()
        
        try:
            choice = console.input(f"[info]Select preset to toggle [1-{len(provider.presets)}] (0 to clear, Enter to return):[/info] ").strip()
        except (EOFError, KeyboardInterrupt):
            return
            
        if not choice:
            return
            
        if choice.isdigit():
            idx = int(choice)
            if idx == 0:
                provider.active_presets.clear()
                console.print("[success] All filters cleared.[/success]")
            elif 1 <= idx <= len(provider.presets):
                preset = provider.presets[idx - 1]
                if preset in provider.active_presets:
                    provider.active_presets.remove(preset)
                    console.print(f"[success] Removed preset: {preset.name}[/success]")
                else:
                    provider.active_presets.append(preset)
                    console.print(f"[success] Activated preset: {preset.name}[/success]")
            else:
                console.print("[warning] Invalid choice.[/warning]")
        else:
            console.print("[warning] Invalid choice.[/warning]")


def print_banner() -> None:
    """Display the app banner."""
    banner = Text()
    banner.append("Torrent Search CLI", style="bold magenta")
    console.print(
        Panel(
            banner,
            border_style="bright_blue",
            padding=(1, 2),
        )
    )
    console.print()


import os

def clear_screen() -> None:
    """Clear the console and reprint the banner to reduce visual pollution."""
    os.system('cls' if os.name == 'nt' else 'clear')
    print_banner()


def download_method_prompt() -> str | None:
    """
    Prompt the user to choose a download method.
    Returns 't' for torrent client, 'd' for direct download, None for cancel.
    """
    wt_available = has_webtorrent()

    client_name = detect_torrent_client()

    console.print("[title]Download method:[/title]")
    console.print(f"  [bold cyan][T][/bold cyan] Open in {client_name}")
    if wt_available:
        console.print("  [bold cyan][D][/bold cyan] Download directly (webtorrent)")
        console.print("      [dim yellow]Will not seed after download. Slower than torrent client.[/dim yellow]")
    else:
        console.print("  [dim][D] Download directly (webtorrent not installed)[/dim]")
    console.print("  [bold cyan][C][/bold cyan] Cancel")
    console.print()

    try:
        choice = console.input("[info]Choose [T/D/C]:[/info] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None

    if choice in ("t", ""):
        return "t"
    elif choice == "d":
        if not wt_available:
            console.print("[error] webtorrent-cli is not installed.[/error]")
            console.print("[info]Install with:[/info] npm install -g webtorrent-cli\n")
            return None
        return "d"
    elif choice == "c":
        return None
    else:
        console.print("[warning] Invalid choice.[/warning]")
        return None


def provider_select_prompt() -> object | None:
    """Prompt the user to select a torrent provider. Returns the provider object or None if cancelled."""
    clear_screen()
    console.print("[title]Select Provider:[/title]")
    
    options = []
    for i, p in enumerate(PROVIDERS, 1):
        options.append(f"[{i}] {p.label}")
        
    console.print("    ".join(options))
    console.print()
    
    max_choice = len(PROVIDERS)
    
    while True:
        try:
            choice = console.input(f"[info]Choose [1-{max_choice}] (default 1):[/info] ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
            
        if not choice:
            return PROVIDERS[0]
            
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(PROVIDERS):
                return PROVIDERS[idx]
                
        console.print("[warning] Invalid choice. Try again.[/warning]")

