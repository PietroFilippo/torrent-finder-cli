"""Local-file transfer UI: preview first, then one explicit transaction."""

# i18n: converted
from torrent_finder.i18n import t, tn


from rich.markup import escape
from torrent_finder import settings_backup as backup, store
from torrent_finder.ui.selector import SelectItem, arrow_select


def backup_menu():
    from torrent_finder.ui.prompts import PROMPT, confirm_prompt, get_query_with_shortcut, input_screen
    from torrent_finder import credentials
    message, restored = "", False
    while True:
        options = [SelectItem(t("Export settings (no history or credentials)"), "export"),
                   SelectItem(t("Export settings with history (no credentials)"), "export_history"),
                   SelectItem(t("Import settings — preview first"), "import"),
                   SelectItem(t("Export credentials separately…"), "export_credentials",
                              description=t("Explicit secret transfer. Plaintext file; contains saved passwords/API keys, never environment values.")),
                   SelectItem(t("Import credentials separately…"), "import_credentials",
                              description=t("Changes only saved credentials. Environment overrides continue to take precedence.")),
                   SelectItem(t("Back"), "back")]
        pick = arrow_select(options, title=t("Settings backup / transfer"), footer=escape(message) or t("Local JSON files • Enter choose • Esc back"))
        if pick is None or options[pick].value == "back":
            return restored
        action = options[pick].value
        titles = {"export": t("Export settings"), "export_history": t("Export settings with history"),
                  "import": t("Import settings"), "export_credentials": t("Export credentials"),
                  "import_credentials": t("Import credentials")}
        help_lines = [t("Local JSON file path.")]
        if action.startswith("export"):
            help_lines.append(t("Choose a new file name; existing files are never overwritten."))
        elif action == "import":
            help_lines.append(t("A preview comes before anything changes."))
        path = get_query_with_shortcut(PROMPT, screen_renderer=input_screen(titles.get(action, t("Settings backup")),
                                                                             *help_lines))
        if not isinstance(path, str) or path == "GO_BACK" or not path.strip():
            continue
        path = path.strip().strip('"')
        try:
            if action.startswith("export"):
                if action == "export_credentials":
                    if not confirm_prompt(t("Write saved passwords/API keys to a separate plaintext file?"), title=t("Export credentials")):
                        continue
                    backup.export_credentials(path)
                else:
                    backup.export_settings(path, history=action == "export_history")
                message = t("Export saved: {path}", path=path)
                continue
            secret = action == "import_credentials"
            data = backup.read_backup(path, credentials=secret)
            modes = [SelectItem(t("Merge"), "merge", description=t("Imported entries win conflicts; retain other entries. Profiles match by name; current active profile stays.")),
                     SelectItem(t("Replace"), "replace", description=t("Replace portable settings, or the separate credential collection. Stats/bookmarks/machine settings stay. Omitted history stays.")),
                     SelectItem(t("Cancel"), "cancel")]
            chosen = arrow_select(modes, title=t("Restoration behavior"), footer=t("Enter preview • Esc cancel"))
            if chosen is None or modes[chosen].value == "cancel":
                continue
            mode = modes[chosen].value
            if secret:
                summary = (tn("Merge saved credentials: {n} field", "Merge saved credentials: {n} fields", len(data))
                           if mode == "merge" else
                           tn("Replace saved credentials: {n} field", "Replace saved credentials: {n} fields", len(data)))
                changes = [summary, t("Fields: {fields}", fields=", ".join(data)),
                           t("Environment overrides stay active. Settings/history will not change.")]
            else:
                _, changes = backup.prepare_import(data, mode)
            preview = [SelectItem(line, passive=True) for line in changes]
            preview += [SelectItem(t("Apply import"), "apply"), SelectItem(t("Cancel"), "cancel")]
            choice = arrow_select(preview, title=t("Import preview"), footer=t("Review with arrows • Enter apply/cancel • Esc cancel"))
            if choice is None or preview[choice].value != "apply":
                continue
            if secret:
                credentials.import_file_values(data, replace=mode == "replace")
            else:
                store.commit(backup.import_change(data, mode))
                restored = True
            message = t("Import complete.")
        except (OSError, ValueError, TypeError) as error:
            message = t("Transfer failed: {error}", error=str(error))
