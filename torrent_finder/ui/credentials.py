"""Interactive rendering and workflows for the credentials registry."""

import sys

import readchar
from rich.cells import cell_len
from rich.markup import escape
from rich.console import Group
from rich.text import Text

from torrent_finder.constants import console
from torrent_finder.credential_registry import CREDENTIAL_REGISTRY, CredentialField, CredentialSpec
from torrent_finder.ui import theme
from torrent_finder.ui.layout import ellipsize_cells
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
    notes.append("Stored in plaintext in subtitle_credentials.json")
    footer = "Type to edit the focused field.\n↑/↓ move  •  Tab next  •  Enter next field / choose  •  Esc cancel"

    def _field_text(field: CredentialField, focused: bool) -> str:
        buf = buffers.get(field.env_key, "")
        if focused:
            shown = ("*" * len(buf)) if field.secret else buf
            text = f"{field.label}: {shown}█"
            room = theme.inner_width(console.size.width) - 2  # inside the cursor gutter
            if cell_len(text) <= room:
                return text
            # Too long for one row: keep a short label and the end of the value,
            # so what is being typed and the caret stay visible.
            prefix = ellipsize_cells(field.label, max(6, room // 3)) + ": …"
            tail, cells = "", 0
            for char in reversed(shown):
                if cells + cell_len(char) > max(1, room - cell_len(prefix) - 1):
                    break
                tail, cells = char + tail, cells + cell_len(char)
            return f"{prefix}{tail}█"
        if buf:
            shown = ("*" * len(buf)) if field.secret else buf
            return f"{field.label}: {shown}"
        current = field.value()
        if current:
            shown = ("*" * 8) if field.secret else current
            return f"{field.label}: {shown}  (unchanged)"
        return f"{field.label}: not set"

    def _row(label: str, focused: bool) -> Text:
        row = Text(theme.MARGIN, no_wrap=True, overflow="ellipsis")
        row.append(theme.CURSOR if focused else " ", style=theme.ACCENT)
        row.append(" ")
        row.append(label, style=theme.FOCUS if focused else "")
        return row

    def _panel() -> Group:
        """The sign-in frame, fitted to the window.

        In a small window the how-to steps shorten first, then the blank lines,
        the notes and the header's second line go; as a last resort the fields
        scroll around the focused one. The focused field and the keys stay.
        """
        width, height = console.size.width, console.size.height
        compact = not theme.roomy(height, 20)
        parsed = theme.parse_footer(footer)
        title = f"Credentials › {meta.name} — sign in"
        top = theme.header_lines(title, "", width)
        guide: list[Text] = []
        if meta.howto:
            guide.append(Text(theme.MARGIN + "HOW TO GET THIS", style=theme.SECTION))
            for step_no, step in enumerate(meta.howto, 1):
                guide.extend(theme.wrap_block(Text(f"{step_no}. {step}", style=theme.MUTED), width, console))
            if meta.tip:
                tip = Text("Tip  ", style=theme.ACCENT)
                tip.append(meta.tip, style=theme.MUTED)
                guide.extend(theme.wrap_block(tip, width, console))
        selectable = [_row(_field_text(field, focus == index), focus == index) for index, field in enumerate(fields)]
        selectable += [_row("Save", focus == save_row), _row("Cancel", focus == cancel_row)]
        prose = theme.wrap_block(Text(" · ".join(notes), style=theme.MUTED), width, console)
        for line in parsed.context:
            prose += theme.wrap_block(line, width, console)
        keys_lines = theme.wrap_keys(parsed.keys, width)
        # Blank lines: after the header, after the guide, before Save, before the notes, before the keys.
        gaps = [not compact, True, True, True, not compact]

        def size(with_guide: bool = True) -> int:
            return (len(top) + (len(guide) if with_guide else 0) + len(selectable) + len(prose)
                    + len(keys_lines) + sum(gaps[:1]) + (gaps[1] and bool(guide) and with_guide)
                    + sum(gaps[2:]))

        if size() > height:
            room = height - size(with_guide=False) - gaps[1]
            guide = [] if room <= 0 else guide[:room - 1] + [Text(theme.MARGIN + "…", style=theme.MUTED)] \
                if room < len(guide) else guide
        if size() > height:
            gaps = [False] * 5
        if size() > height:
            prose = []
        if size() > height and len(top) > 1:
            top = [theme.header(title, "", width)]
        first = 0
        if size() > height:  # scroll the fields around the focused one
            visible = max(1, height - len(top) - len(keys_lines))
            first = min(max(0, focus - visible // 2), max(0, len(selectable) - visible))
            selectable = selectable[first:first + visible]
            guide = []

        blank, rule = Text(""), theme.rule(width)
        fields_part = selectable[:max(0, n - first)]
        actions_part = selectable[max(0, n - first):]
        lines = list(top) + ([rule] if gaps[0] else []) + guide + ([blank] if gaps[1] and guide else [])
        lines += fields_part + ([blank] if gaps[2] and fields_part and actions_part else []) + actions_part
        lines += ([blank] if gaps[3] and prose else []) + prose + ([rule] if gaps[4] else []) + keys_lines
        return Group(*lines)

    sys.stdout.write("\033[?1049h\033[?25l\033[2J\033[H")
    sys.stdout.flush()
    try:
        _render(_make_banner_panel(), _panel())
        while True:
            try:
                key = readchar.readkey()
            except KeyboardInterrupt:
                return None
            if key in (readchar.key.ESC, readchar.key.CTRL_C, "\x03"):
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
            elif len(key) == 1 and key >= " " and not key.startswith(("\x1b", "\x00", "\xe0")):
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
        console.print("[muted]Press [key]any key[/key] to continue…[/muted]")
        readchar.readkey()
        return True

    effective = meta.effective_values(entered)
    missing = meta.missing_required(effective)
    if missing:
        labels = ", ".join(field.label for field in missing)
        console.print(f"[warning]Required field(s) missing: {labels}.[/warning]")
        console.print("[muted]Press [key]any key[/key] to continue…[/muted]")
        readchar.readkey()
        return False

    try:
        with console.status("[accent]Verifying credentials…[/accent]", spinner="dots"):
            ok, message = meta.verify(effective)
    except KeyboardInterrupt:
        console.print("[warning]Verification cancelled — nothing saved.[/warning]")
        return False
    except Exception as error:  # a verifier bug must not end the app
        ok, message = None, f"Couldn't verify ({type(error).__name__})"
    if ok is True:
        console.print(f"[success]✓ Verified: {escape(message)}[/success]")
    elif ok is None:
        console.print(f"[warning]{escape(message)}[/warning]")
    else:
        console.print(f"[error]✗ Verification failed: {escape(message)}[/error]")
        if not _inline_confirm(
            "Save these credentials anyway? — Y/Yes to save, anything else cancels:"
        ):
            console.print("[warning]Not saved.[/warning]")
            console.print("[muted]Press [key]any key[/key] to continue…[/muted]")
            readchar.readkey()
            return False

    try:
        meta.save(entered)
    except (OSError, ValueError):
        console.print("[error]Could not save credentials. The existing file was preserved; check its permissions and JSON format.[/error]")
        readchar.readkey()
        return False
    console.print(f"[success]Saved {meta.name} credentials.[/success]")
    console.print("[muted]Press [key]any key[/key] to continue…[/muted]")
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
        return "Hide password / API key" if state["revealed"] else "Show password / API key"

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
    items.append(SelectItem(label="Back", value="back", is_action=True))

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
        title=f"Credentials › {meta.name} — stored credentials",
        banner=_make_banner_panel(),
        footer="Secrets are masked — pick Show password / API key to reveal.",
        on_action=on_action,
    )


def _manage_credentials(meta: CredentialSpec) -> None:
    """View, enter/update, or clear one registry entry."""
    while True:
        items = [
            SelectItem(label="View credentials", value="view", is_action=True),
            SelectItem(label="Enter / update credentials", value="edit", is_action=True),
        ]
        if meta.has_any_credentials():
            items.append(SelectItem(
                label="Clear stored credentials", value="clear", is_action=True
            ))
        items.append(SelectItem(label="Back", value="back", is_action=True))

        index = arrow_select(
            items,
            title=f"Credentials › {meta.name}",
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
            try:
                meta.clear_saved()
            except (OSError, ValueError):
                console.print("[error]Could not clear credentials; the existing file was preserved.[/error]")
                readchar.readkey()
                continue
            console.print(f"[success]Cleared {meta.name} credentials from the file.[/success]")
            overrides = meta.environment_override_keys()
            if overrides:
                console.print(
                    "[warning]Still set via environment (overrides the file): "
                    + ", ".join(overrides)
                    + ".[/warning]"
                )
                console.print("[dim]Unset those environment variables to fully remove them.[/dim]")
            console.print("[muted]Press [key]any key[/key] to continue…[/muted]")
            readchar.readkey()


def credentials_menu() -> None:
    """Render all credential entries grouped by registry category."""
    from torrent_finder.credentials import storage_problem
    from rich.markup import escape
    while True:
        problem = storage_problem()
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
                label=meta.name,
                value=meta,
                is_action=True,
                hint=meta.status(),
                description=meta.limit or "No notable daily limit.",
            ))
        items.append(SelectItem(label="Back", value="__back__", is_action=True))

        index = arrow_select(
            items,
            title="Credentials",
            banner=_make_banner_panel(),
            footer=(
                (escape(problem) + "\n" if problem else "")
                + "Stored in subtitle_credentials.json (gitignored, plaintext) — "
                "holds all of these. Env vars override the file."
            ),
            start_index=1,
        )
        if index is None or items[index].value == "__back__":
            return
        _manage_credentials(items[index].value)
