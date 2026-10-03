"""Search evidence and explicit retry/page controls, including empty searches."""

import threading

from rich.text import Text

from torrent_finder.constants import console
from torrent_finder.ui.prompts import _make_banner_panel
from torrent_finder.ui.selector import SelectItem, arrow_select
from torrent_finder.utils import start_esc_listener


def read_details(text, title="Search details"):
    """Scroll complete evidence as rows so long errors fit tiny viewports."""
    lines = Text(text).wrap(console, max(12, console.size.width - 12))
    items = [SelectItem(line.plain or " ", passive=True) for line in lines]
    items.append(SelectItem("Back", is_action=True))
    arrow_select(items, title=title, banner=_make_banner_panel(), footer="↑/↓ scroll • Esc back")


def run_action(session, action):
    """Wait for the bounded coordinator to freeze a cancelled/partial action."""
    cancel, finish, done = threading.Event(), threading.Event(), threading.Event()
    out = {}

    def work():
        try:
            out["results"] = session.run(action, cancel_event=cancel, finish_event=finish)
        except Exception:
            out["error"] = "Search action failed; earlier results are retained."
        finally:
            done.set()

    threading.Thread(target=work, daemon=True).start()
    stop = start_esc_listener(cancel, finish_event=finish)
    try:
        label = "Retrying failed sources" if action == "retry" else "Loading more results"
        with console.status(label + " · Enter: results so far · Esc: stop", spinner="dots"):
            while not done.wait(0.05):
                pass
    except KeyboardInterrupt:
        cancel.set()
        done.wait(0.5)
    finally:
        stop.set()
    return out.get("results"), out.get("error", "")


def diagnostics_menu(session):
    from torrent_finder.credential_registry import CREDENTIAL_REGISTRY
    while True:
        items = [
            SelectItem("Retry failed sources", value="retry", enabled=session.can_retry,
                       description="Keep received results and retry failures. Required filters stay active."),
            SelectItem("Load more results", value="more", enabled=session.can_load_more,
                       description="One more page per supported source/query; up to 24 per action."),
            SelectItem("Credentials / verify login", value="credentials",
                       description="Saved credentials are not verified login. Open to verify or edit."),
            SelectItem(f"Names searched ({len(session.queries)})", value=("names", "\n".join(session.queries)),
                       description="Read the complete query list. Preset expansions appear on the individual source attempts."),
        ]
        for spec in CREDENTIAL_REGISTRY:
            if spec.id in {"rutracker", "madokami", "online_fix"} and any(
                spec.name.casefold().replace("-", "") in d.engine.casefold().replace("-", "") for d in session.diagnostics
            ):
                items.append(SelectItem(spec.name + ": " + spec.status(), passive=True,
                                        description="Configuration status only. Open Credentials to verify; search failures appear below."))
        for d in session.diagnostics:
            items.append(SelectItem(f"{d.provider} / {d.engine}: {d.status.replace('_', ' ')}", value=d,
                                    description=f"{d.raw} returned / {d.kept} kept · {d.seconds:.1f}s\nEnter for query, filters and errors."))
        for line in session.page_status():
            items.append(SelectItem("Pages: " + line, value=("pages", line),
                                    description="Enter for full pagination status."))
        items.append(SelectItem("Back to results", value=None, is_action=True))
        idx = arrow_select(items, title="Search diagnostics", banner=_make_banner_panel(),
                           footer="↑/↓ read • Enter action • Esc results")
        if idx is None or items[idx].value is None:
            return None
        action = items[idx].value
        if not isinstance(action, str):
            read_details(action[1] if isinstance(action, tuple) else action.describe())
            continue
        if action == "credentials":
            from torrent_finder.ui.credentials import credentials_menu
            credentials_menu()
        else:
            return action
