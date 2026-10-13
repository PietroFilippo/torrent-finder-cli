"""Terminal-command preset selector and launcher installation feedback."""

# i18n: converted
import os
import sys

from rich.markup import escape

from torrent_finder.i18n import N_, t
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
    DEFAULT_COMMAND: N_("Canonical command installed by the package."),
    "tf": N_("Shortest quick-launch command."),
    "torrent": N_("Readable short form; also included with pip and pipx installs."),
    "find-torrent": N_("Explicit name with a low chance of colliding with another tool."),
    "tfind": N_("Compact while remaining distinctive."),
}


def _command_items(selected: str, available: bool) -> list[SelectItem]:
    items = []
    for name in COMMAND_CHOICES:
        is_current = name == selected
        description = t(_DESCRIPTIONS[name])
        hint = ""
        if is_current:
            hint = t("current") if available else t("not on PATH yet")
            if not available:  # what the command is first, then what to do about its status
                description += t("\nSelected, but the launcher is not on PATH yet: open a new terminal, or add its folder to PATH.")
        items.append(SelectItem(
            label=f"{'✓' if is_current else ' '}  {name}",
            value=name,
            hint=hint,
            is_action=True,
            description=description,
        ))
    items.append(SelectItem(label=t("Back"), value="back", is_action=True))
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
            title=t("Terminal Command"),
            footer=(
                (notice + "\n" if notice else "")
                + t("↑/↓ navigate  •  Enter select  •  Esc go back")
            ),
            start_index=start,
        )
        if result is None or items[result].value == "back":
            return

        selected = items[result].value
        try:
            updated = set_terminal_command(selected)
        except LauncherConflict as exc:
            notice = t("[warning]Not changed:[/warning] {error}", error=escape(str(exc)))
            continue
        except LauncherError as exc:
            notice = t("[error]Could not install command:[/error] {error}", error=escape(str(exc)))
            continue

        if selected == DEFAULT_COMMAND:
            notice = t("[success]Using torrent-finder.[/success] Managed quick-launch alias removed.")
            continue

        if updated.path_ready:
            notice = (
                t("[success]{command} is ready.[/success] "
                  "It forwards every option to torrent-finder.", command=escape(selected))
            )
            continue

        directory = os.path.dirname(updated.path) or launcher_dir()
        if sys.platform == "win32":
            from torrent_finder.ui.prompts import confirm_prompt

            add_path = confirm_prompt(
                t("[bold]Add the launcher folder to your Windows user PATH?[/bold]\n\n"
                  "{directory}\n\n"
                  "This affects new terminals only and does not require administrator access.",
                  directory=escape(directory))
            )
            if add_path and ensure_launcher_dir_on_path(directory):
                notice = (
                    t("[success]{command} is installed.[/success] "
                      "Open a new terminal before using it.", command=escape(selected))
                )
            else:
                notice = (
                    t("[warning]{command} was created but is not on PATH.[/warning] "
                      "Add {directory} to PATH to use it.", command=escape(selected), directory=escape(directory))
                )
        else:
            notice = (
                t("[warning]{command} was created but is not on PATH.[/warning] "
                  "Add {directory} to PATH in your shell profile.", command=escape(selected), directory=escape(directory))
            )


__all__ = ["terminal_command_prompt"]
