"""Local-file transfer UI: preview first, then one explicit transaction."""

from rich.markup import escape
from torrent_finder import settings_backup as backup, store
from torrent_finder.ui.selector import SelectItem, arrow_select


def backup_menu():
    from torrent_finder.ui.prompts import PROMPT, confirm_prompt, get_query_with_shortcut, input_screen
    from torrent_finder import credentials
    message, restored = "", False
    while True:
        options = [SelectItem("Export settings (no history or credentials)", "export"),
                   SelectItem("Export settings with history (no credentials)", "export_history"),
                   SelectItem("Import settings — preview first", "import"),
                   SelectItem("Export credentials separately…", "export_credentials",
                              description="Explicit secret transfer. Plaintext file; contains saved passwords/API keys, never environment values."),
                   SelectItem("Import credentials separately…", "import_credentials",
                              description="Changes only saved credentials. Environment overrides continue to take precedence."),
                   SelectItem("Back", "back")]
        pick = arrow_select(options, title="Settings backup / transfer", footer=escape(message) or "Local JSON files • Enter choose • Esc back")
        if pick is None or options[pick].value == "back":
            return restored
        action = options[pick].value
        titles = {"export": "Export settings", "export_history": "Export settings with history",
                  "import": "Import settings", "export_credentials": "Export credentials",
                  "import_credentials": "Import credentials"}
        help_lines = ["Local JSON file path."]
        if action.startswith("export"):
            help_lines.append("Choose a new file name; existing files are never overwritten.")
        elif action == "import":
            help_lines.append("A preview comes before anything changes.")
        path = get_query_with_shortcut(PROMPT, screen_renderer=input_screen(titles.get(action, "Settings backup"),
                                                                             *help_lines))
        if not isinstance(path, str) or path == "GO_BACK" or not path.strip():
            continue
        path = path.strip().strip('"')
        try:
            if action.startswith("export"):
                if action == "export_credentials":
                    if not confirm_prompt("Write saved passwords/API keys to a separate plaintext file?", title="Export credentials"):
                        continue
                    backup.export_credentials(path)
                else:
                    backup.export_settings(path, history=action == "export_history")
                message = "Export saved: " + path
                continue
            secret = action == "import_credentials"
            data = backup.read_backup(path, credentials=secret)
            modes = [SelectItem("Merge", "merge", description="Imported entries win conflicts; retain other entries. Profiles match by name; current active profile stays."),
                     SelectItem("Replace", "replace", description="Replace portable settings, or the separate credential collection. Stats/bookmarks/machine settings stay. Omitted history stays."),
                     SelectItem("Cancel", "cancel")]
            chosen = arrow_select(modes, title="Restoration behavior", footer="Enter preview • Esc cancel")
            if chosen is None or modes[chosen].value == "cancel":
                continue
            mode = modes[chosen].value
            if secret:
                changes = [f"{mode.title()} saved credentials: {len(data)} fields",
                           "Fields: " + ", ".join(data), "Environment overrides stay active. Settings/history will not change."]
            else:
                _, changes = backup.prepare_import(data, mode)
            preview = [SelectItem(line, passive=True) for line in changes]
            preview += [SelectItem("Apply import", "apply"), SelectItem("Cancel", "cancel")]
            choice = arrow_select(preview, title="Import preview", footer="Review with arrows • Enter apply/cancel • Esc cancel")
            if choice is None or preview[choice].value != "apply":
                continue
            if secret:
                credentials.import_file_values(data, replace=mode == "replace")
            else:
                store.commit(backup.import_change(data, mode))
                restored = True
            message = "Import complete."
        except (OSError, ValueError, TypeError) as error:
            message = "Transfer failed: " + str(error)
