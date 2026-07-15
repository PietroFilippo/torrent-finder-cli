"""Interactive rendering and workflows for the credentials registry."""

import sys

import readchar
from rich.panel import Panel
from rich.text import Text

from torrent_finder.constants import console
from torrent_finder.credential_registry import CREDENTIAL_REGISTRY, CredentialField, CredentialSpec
from torrent_finder.ui.prompts import _make_banner_panel, confirm_prompt
from torrent_finder.ui.selector import SelectItem, _render, arrow_select


def _credentials_form(meta: CredentialSpec, buffers: dict[str, str]) -> dict[str, str] | None:
    """Edit every field inline; return buffers on Save or None on cancel."""
    fields = meta.fields
    n = len(fields)
    save_row, cancel_row = n, n + 1
    focus = 0

    notes = []
    if meta.limit:
        notes.append(meta.limit)
    if any(field.env_override() for field in meta.required_fields):
        notes.append("Env var overrides the saved file")
    notes.append("Type to edit • ↑/↓ or Tab move • Enter on a field = next • Esc cancels")
    notes.append("Stored in plaintext in subtitle_credentials.json")
    footer = "  •  ".join(notes)

    def _field_text(field: CredentialField, focused: bool) -> str:
        buf = buffers.get(field.env_key, "")
        if focused:
            shown = ("*" * len(buf)) if field.secret else buf
            return f"{field.label}: {shown}█"
        if buf:
            shown = ("*" * len(buf)) if field.secret else buf
            return f"{field.label}: {shown}"
        current = field.value()
        if current:
            shown = ("*" * 8) if field.secret else current
            return f"{field.label}: {shown}  (unchanged)"
        return f"{field.label}: not set"

    def _panel() -> Panel:
        body = Text()
        if meta.howto:
            body.append("  How to get this:\n", style="bold")
            for step_no, step in enumerate(meta.howto, 1):
                body.append(f"   {step_no}. {step}\n", style="dim")
            if meta.tip:
                body.append(f"   💡 {meta.tip}\n", style="yellow")
            body.append("  " + "─" * 25 + "\n", style="dim")
        for index, field in enumerate(fields):
            focused = focus == index
            style = "bold cyan" if focused else "white"
            body.append("  ❯ " if focused else "    ", style=style)
            body.append(_field_text(field, focused), style=style)
            body.append("\n")
        body.append("  " + "─" * 25 + "\n", style="dim")
        for row, label in ((save_row, "✅  Save"), (cancel_row, "↩  Cancel")):
            style = "bold cyan" if focus == row else "white"
            body.append("  ❯ " if focus == row else "    ", style=style)
            body.append(label, style=style)
            body.append("\n")
        body.append("\n")
        body.append_text(Text.from_markup(f" {footer}", style="dim"))
        return Panel(
            body,
            title=f"[bold magenta]{meta.icon} {meta.name} — sign in[/bold magenta]",
            border_style="bright_blue",
            padding=(1, 2),
        )

    sys.stdout.write("\033[?1049h\033[?25l\033[2J\033[H")
    sys.stdout.flush()
    try:
        _render(_make_banner_panel(), _panel())
        while True:
            try:
                key = readchar.readkey()
            except KeyboardInterrupt:
                return None
            if key == readchar.key.ESC:
                return None
            if key == readchar.key.UP:
                focus = (focus - 1) % (n + 2)
            elif key in (readchar.key.DOWN, "\t"):
                focus = (focus + 1) % (n + 2)
            elif key in (readchar.key.ENTER, readchar.key.CR, readchar.key.LF):
                if focus == cancel_row:
                    return None
                if focus == save_row:
                    return buffers
                focus = (focus + 1) % (n + 2)
            elif key in (readchar.key.BACKSPACE, "\x08", "\x7f"):
                if focus < n:
                    env_key = fields[focus].env_key
                    if buffers.get(env_key):
                        buffers[env_key] = buffers[env_key][:-1]
            elif len(key) == 1 and not key.startswith(("\x1b", "\x00", "\xe0")):
                if focus < n:
                    env_key = fields[focus].env_key
                    buffers[env_key] = buffers.get(env_key, "") + key
            _render(_make_banner_panel(), _panel())
    finally:
        sys.stdout.write("\033[?25h\033[?1049l\033[2J\033[H")
        sys.stdout.flush()


def _inline_confirm(message: str, default: bool = False) -> bool:
    """Inline y/N confirmation printed in the current flow."""
    try:
        answer = console.input(f"[warning]{message}[/warning] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if not answer:
        return default
    return answer in ("y", "yes")


def _finalize_credentials_save(meta: CredentialSpec, entered: dict[str, str]) -> bool:
    """Validate, verify, and save entered values; False reopens the form."""
    if not entered:
        console.print("[dim]No changes entered — existing credentials kept, nothing saved.[/dim]")
        console.print("[dim]Press any key to continue...[/dim]")
        readchar.readkey()
        return True

    effective = meta.effective_values(entered)
    missing = meta.missing_required(effective)
    if missing:
        labels = ", ".join(field.label for field in missing)
        console.print(f"[warning]Required field(s) missing: {labels}.[/warning]")
        console.print("[dim]Press any key to continue...[/dim]")
        readchar.readkey()
        return False

    with console.status("[bold cyan]Verifying credentials…[/bold cyan]", spinner="dots"):
        ok, message = meta.verify(effective)
    if ok is True:
        console.print(f"[success]✓ Verified: {message}[/success]")
    elif ok is None:
        console.print(f"[warning]⚠  {message}[/warning]")
    else:
        console.print(f"[error]✗ Verification failed: {message}[/error]")
        if not _inline_confirm(
            "Save these credentials anyway? — Y/Yes to save, anything else cancels:"
        ):
            console.print("[warning]Not saved.[/warning]")
            console.print("[dim]Press any key to continue...[/dim]")
            readchar.readkey()
            return False

    meta.save(entered)
    console.print(f"[success]Saved {meta.name} credentials.[/success]")
    console.print("[dim]Press any key to continue...[/dim]")
    readchar.readkey()
    return True


def _edit_credentials(meta: CredentialSpec) -> None:
    buffers: dict[str, str] = {}
    while True:
        result = _credentials_form(meta, buffers)
        if result is None:
            return
        entered = {key: value.strip() for key, value in result.items() if value.strip()}
        if _finalize_credentials_save(meta, entered):
            return


def _view_field_label(field: CredentialField, revealed: bool) -> str:
    """Render one stored credential row as plain text."""
    value = field.value()
    if not value:
        return f"{field.label}: not set"
    shown = value if (revealed or not field.secret) else "*" * 8
    source = {"env": "from environment", "file": "from file"}.get(field.source(), "")
    return f"{field.label}: {shown}" + (f"   [{source}]" if source else "")


def _view_credentials(meta: CredentialSpec) -> None:
    """Show current credentials with a reveal toggle for secret fields."""
    state = {"revealed": False}

    def _toggle_label() -> str:
        return "🙈 Hide password / API key" if state["revealed"] else "👁  Show password / API key"

    items = [
        SelectItem(
            label=_view_field_label(field, False),
            value=("field", field.env_key),
            enabled=False,
            is_action=True,
        )
        for field in meta.fields
    ]
    items.append(SelectItem(label="", value="__sep__", enabled=False, is_action=True))
    items.append(SelectItem(
        label=_toggle_label(),
        value="toggle",
        is_action=True,
        description="Reveal or hide the stored password / API key.",
    ))
    items.append(SelectItem(label="↩  Back", value="back", is_action=True))

    def on_action(index, menu_items):
        if menu_items[index].value != "toggle":
            return False
        state["revealed"] = not state["revealed"]
        for field_index, field in enumerate(meta.fields):
            menu_items[field_index].label = _view_field_label(field, state["revealed"])
        menu_items[index].label = _toggle_label()
        return True

    arrow_select(
        items,
        title=f"{meta.icon} {meta.name} — stored credentials",
        banner=_make_banner_panel(),
        footer="Secrets are masked — pick Show password / API key to reveal.",
        on_action=on_action,
    )


def _manage_credentials(meta: CredentialSpec) -> None:
    """View, enter/update, or clear one registry entry."""
    while True:
        items = [
            SelectItem(label="👁  View credentials", value="view", is_action=True),
            SelectItem(label="✏  Enter / update credentials", value="edit", is_action=True),
        ]
        if meta.has_any_credentials():
            items.append(SelectItem(
                label="🗑  Clear stored credentials", value="clear", is_action=True
            ))
        items.append(SelectItem(label="↩  Back", value="back", is_action=True))

        index = arrow_select(
            items,
            title=f"{meta.icon} {meta.name}",
            banner=_make_banner_panel(),
        )
        if index is None:
            return
        action = items[index].value
        if action == "back":
            return
        if action == "view":
            _view_credentials(meta)
        elif action == "edit":
            _edit_credentials(meta)
        elif action == "clear" and confirm_prompt(f"Clear stored {meta.name} credentials?"):
            meta.clear_saved()
            console.print(f"[success]Cleared {meta.name} credentials from the file.[/success]")
            overrides = meta.environment_override_keys()
            if overrides:
                console.print(
                    "[warning]Still set via environment (overrides the file): "
                    + ", ".join(overrides)
                    + ".[/warning]"
                )
                console.print("[dim]Unset those environment variables to fully remove them.[/dim]")
            console.print("[dim]Press any key to continue...[/dim]")
            readchar.readkey()


def credentials_menu() -> None:
    """Render all credential entries grouped by registry category."""
    while True:
        items = []
        last_category = None
        for meta in CREDENTIAL_REGISTRY:
            if meta.category != last_category:
                items.append(SelectItem(
                    label=f"─── {meta.category} ───",
                    value="section_header",
                    enabled=False,
                    is_action=True,
                ))
                last_category = meta.category
            items.append(SelectItem(
                label=f"{meta.icon} {meta.name}",
                value=meta,
                is_action=True,
                hint=meta.status(),
                description=meta.limit or "No notable daily limit.",
            ))
        items.append(SelectItem(label="↩  Back", value="__back__", is_action=True))

        index = arrow_select(
            items,
            title="Credentials",
            banner=_make_banner_panel(),
            footer=(
                "Stored in subtitle_credentials.json (gitignored, plaintext) — "
                "holds all of these. Env vars override the file."
            ),
            start_index=1,
        )
        if index is None or items[index].value == "__back__":
            return
        _manage_credentials(items[index].value)
