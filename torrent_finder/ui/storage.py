"""Recovery screen for saved settings that could not be read at startup."""

# i18n: converted
import readchar
from rich.markup import escape

from torrent_finder import store
from torrent_finder.constants import console
from torrent_finder.i18n import t
from torrent_finder.ui.selector import SelectItem, arrow_select


def storage_problem_prompt() -> None:
    """Offer recovery while saved settings are unreadable; return when resolved or skipped.

    Nothing is written while the problem lasts: continuing runs this session
    on defaults and leaves the file exactly as it is for a later run.
    """
    notice = ""
    while (problem := store.problem()) is not None:
        items = []
        if problem.damaged:
            items.append(SelectItem(t("Keep a copy and start fresh"), "aside",
                                    description=t("Renames the file; nothing is deleted.")))
        items.append(SelectItem(t("Try again"), "retry",
                                description=t("Reads it again, e.g. after closing a program using it.")))
        items.append(SelectItem(t("Continue without saving"), "continue",
                                description=t("Defaults this session; the file stays as it is.")))
        pick = arrow_select(
            items,
            title=t("Saved settings unavailable"),
            footer=(notice + "\n" if notice else "")
            + f"{escape(problem.reason_label().capitalize())}: {escape(problem.path)}\n"
            + t("Nothing is saved until this is resolved.\nEnter choose  •  Esc continue"),
        )
        if pick is None or items[pick].value == "continue":
            return
        if items[pick].value == "retry":
            notice = "" if store.retry_load() else t("[error]Still unreadable.[/error]")
            continue
        try:
            aside = store.set_aside_unreadable()
        except OSError as error:
            notice = t("[error]Could not rename it:[/error] {error}", error=escape(str(error)))
            continue
        console.print(t("[info]The unreadable settings were kept as {path}. "
                        "New settings are saved from now on.[/info]", path=escape(aside)))
        console.print(t("[muted]Press [key]any key[/key] to continue…[/muted]"))
        readchar.readkey()
