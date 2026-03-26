"""User-facing prompts: banner, download method selection."""

from rich.panel import Panel
from rich.text import Text

from constants import console
from downloader import (
    detect_torrent_client,
    download_with_webtorrent,
    has_webtorrent,
    open_magnet,
)


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
