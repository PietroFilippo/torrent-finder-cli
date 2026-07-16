"""Terminal-command preset selector and launcher installation feedback."""

import os
import sys

from torrent_finder.launcher_alias import (
    COMMAND_CHOICES,
    DEFAULT_COMMAND,
    LauncherConflict,
    LauncherError,
    current_status,
    ensure_launcher_dir_on_path,
    launcher_dir,
    set_terminal_command,
)
from torrent_finder.ui.selector import SelectItem, arrow_select


_DESCRIPTIONS = {
    DEFAULT_COMMAND: "Canonical command installed by the package.",
    "tf": "Shortest quick-launch command.",
    "torrent": "Readable short form; also included with pip and pipx installs.",
    "find-torrent": "Explicit name with a low chance of colliding with another tool.",
    "tfind": "Compact while remaining distinctive.",
}


def _command_items(selected: str, available: bool) -> list[SelectItem]:
    items = []
    for name in COMMAND_CHOICES:
        is_current = name == selected
        hint = "current"
        if is_current and not available:
            hint = "selected; launcher is not currently reachable from PATH"
        items.append(SelectItem(
            label=f"{'✓' if is_current else ' '}  {name}",
            value=name,
            hint=hint if is_current else "",
            is_action=True,
            description=_DESCRIPTIONS[name],
        ))
    items.append(SelectItem(label="←  Go back", value="back", is_action=True))
    return items


def terminal_command_prompt() -> None:
    """Choose and install one preferred terminal quick-launch command."""
    notice = ""
    while True:
        status = current_status()
        items = _command_items(status.name, status.available)
        try:
            start = COMMAND_CHOICES.index(status.name)
        except ValueError:
            start = 0

        result = arrow_select(
            items,
            title="Terminal Command",
            footer=(
                (notice + "\n" if notice else "")
                + "↑/↓ navigate  •  Enter select  •  Esc go back"
            ),
            start_index=start,
        )
        if result is None or items[result].value == "back":
            return

        selected = items[result].value
        try:
            updated = set_terminal_command(selected)
        except LauncherConflict as exc:
            notice = f"[bold yellow]Not changed:[/bold yellow] {exc}"
            continue
        except LauncherError as exc:
            notice = f"[bold red]Could not install command:[/bold red] {exc}"
            continue

        if selected == DEFAULT_COMMAND:
            notice = "[bold green]Using torrent-finder.[/bold green] Managed quick-launch alias removed."
            continue

        if updated.path_ready:
            notice = (
                f"[bold green]{selected} is ready.[/bold green] "
                "It forwards every option to torrent-finder."
            )
            continue

        directory = os.path.dirname(updated.path) or launcher_dir()
        if sys.platform == "win32":
            from torrent_finder.ui.prompts import confirm_prompt

            add_path = confirm_prompt(
                "[bold]Add the launcher folder to your Windows user PATH?[/bold]\n\n"
                f"{directory}\n\n"
                "This affects new terminals only and does not require administrator access."
            )
            if add_path and ensure_launcher_dir_on_path(directory):
                notice = (
                    f"[bold green]{selected} is installed.[/bold green] "
                    "Open a new terminal before using it."
                )
            else:
                notice = (
                    f"[bold yellow]{selected} was created but is not on PATH.[/bold yellow] "
                    f"Add {directory} to PATH to use it."
                )
        else:
            notice = (
                f"[bold yellow]{selected} was created but is not on PATH.[/bold yellow] "
                f"Add {directory} to PATH in your shell profile."
            )


__all__ = ["terminal_command_prompt"]
