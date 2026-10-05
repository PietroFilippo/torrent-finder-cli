"""Search evidence and explicit retry/page controls, including empty searches."""

import re
import threading

from rich.markup import escape
from rich.text import Text

from torrent_finder.constants import console
from torrent_finder.ui import theme
from torrent_finder.ui.prompts import _make_banner_panel
from torrent_finder.ui.search_progress import STATUS_WORDS, status_style
from torrent_finder.ui.selector import SelectItem, arrow_select
from torrent_finder.utils import start_esc_listener

_PAGE_LINE = re.compile(r"^(?P<provider>.+?) / (?P<engine>.+?) · (?P<query>.*?): (?P<status>.+)$")
# Page statuses as a few words; the full sentence stays in the row's description.
_PAGE_WORDS = (("next page: ", "next page "), ("page incomplete", "retry first"),
               ("deeper retrieval unavailable", "no deeper pages"), ("Auto not needed", "not needed"),
               ("exhausted", "no more pages"), ("page limit reached", "page limit reached"))


def _word(status: str) -> str:
    return STATUS_WORDS.get(status, status.replace("_", " "))


def _source_label(diagnostic, with_query: bool = False) -> Text:
    """``Movies & Series · Apibay``: the provider in steel, the engine in text colour (and the query)."""
    label = Text.assemble((f"{diagnostic.provider} · ", theme.MUTED), diagnostic.engine)
    if with_query:
        label.append(f" · {diagnostic.query}", style=theme.MUTED)
    return label


def _evidence(diagnostic, state_width: int = 0) -> Text:
    """The state word in its colour, padded to *state_width*, then what backs it: rows kept, time, retry."""
    hint = Text.assemble((_word(diagnostic.status).ljust(state_width), status_style(diagnostic.status)))
    if diagnostic.status in {"results", "empty", "filtered"}:
        facts = f"{diagnostic.kept} of {diagnostic.raw} kept · {diagnostic.seconds:.1f} s"
    elif diagnostic.status in {"off", "auto", "skipped", "pending"}:
        facts = ""
    else:
        facts = f"{diagnostic.seconds:.1f} s · " + ("retryable" if diagnostic.retryable else "not retryable")
    if facts:
        hint.append("  " + facts)
    return hint


def _failed(diagnostics) -> list:
    return [d for d in diagnostics if d.retryable or d.status == "blocked"]


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


def _section(label: str) -> SelectItem:
    return SelectItem(label, value="section_header", enabled=False)


def diagnostics_status(session) -> str:
    """``2 of 3 sources failed`` in yellow, or ``3 sources answered``; counts every attempt that ran."""
    tried = [d for d in session.diagnostics if d.status not in {"off", "auto", "skipped"}]
    failed = _failed(tried)
    if failed:
        return f"[warn]{len(failed)} of {len(tried)} failed[/warn]"
    return f"{len(tried)} source{'s' if len(tried) != 1 else ''} answered"


def _page_item(line: str, with_query: bool = False) -> SelectItem:
    match = _PAGE_LINE.match(line)
    if match is None:
        engine, _, status = line.partition(": ")
        return SelectItem(engine, value=("pages", line), hint=status, description="Enter for full pagination status.")
    status = match["status"]
    short = next((word for prefix, word in _PAGE_WORDS if status.startswith(prefix)), status)
    if short == "next page ":
        short += status.removeprefix("next page: ")
    label = Text.assemble((f"{match['provider']} · ", theme.MUTED), match["engine"])
    if with_query:
        label.append(f" · {match['query']}", style=theme.MUTED)
    return SelectItem(label, value=("pages", line), hint=short,
                      description=f"{escape(status)}\nEnter for full pagination status.")


def diagnostics_menu(session):
    from torrent_finder.credential_registry import CREDENTIAL_REGISTRY
    while True:
        failed = _failed(session.diagnostics)
        pages = session.page_status()
        items = [
            _section("Actions"),
            SelectItem("Retry failed sources", value="retry", enabled=session.can_retry,
                       hint=", ".join(dict.fromkeys(d.engine for d in failed if d.retryable)),
                       description="Keep received results and retry failures. Required filters stay active."),
            SelectItem("Load more results", value="more", enabled=session.can_load_more,
                       hint=(f"{more} source{'s' if more != 1 else ''} with more pages"
                             if (more := sum("next page" in line for line in pages)) else ""),
                       description="One more page per supported source/query; up to 24 per action."),
            SelectItem("Credentials / verify login", value="credentials",
                       description="Saved credentials are not verified login. Open to verify or edit."),
            SelectItem(f"Names searched ({len(session.queries)})", value=("names", "\n".join(session.queries)),
                       hint=" · ".join(session.queries),
                       description="Read the complete query list. Preset expansions appear on the individual source attempts."),
        ]
        logins = [SelectItem(spec.name, passive=True, hint=spec.status(),
                             description="Configuration status only. Open Credentials to verify; search failures appear below.")
                  for spec in CREDENTIAL_REGISTRY
                  if spec.id in {"rutracker", "madokami", "online_fix"} and any(
                      spec.name.casefold().replace("-", "") in d.engine.casefold().replace("-", "")
                      for d in session.diagnostics)]
        if logins:
            items += [_section("Logins"), *logins]
        if session.diagnostics:
            items.append(_section("Sources"))
            state_width = max(len(_word(d.status)) for d in session.diagnostics)
            several = len(session.queries) > 1
            for d in session.diagnostics:
                items.append(SelectItem(_source_label(d, several), value=d, hint=_evidence(d, state_width),
                                        description=f"Query: {escape(d.query)}\nEnter for query, filters and errors."))
        if pages:
            items.append(_section("Pages"))
            items += [_page_item(line, len(session.queries) > 1) for line in pages]
        items.append(SelectItem("Back to results", value=None, is_action=True))
        names = escape(", ".join(session.queries))
        idx = arrow_select(items, title="Search diagnostics" + (f" › {names}" if names else ""),
                           status=diagnostics_status(session), banner=_make_banner_panel(),
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
