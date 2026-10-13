"""Search evidence and explicit retry/page controls, including empty searches."""

# i18n: converted
import re
import threading

from rich.cells import cell_len
from rich.markup import escape
from rich.text import Text

from torrent_finder.constants import console
from torrent_finder.i18n import N_, t, tn
from torrent_finder.search_session import PageStatus
from torrent_finder.ui import theme
from torrent_finder.ui.prompts import _make_banner_panel
from torrent_finder.ui.search_progress import status_style
from torrent_finder.ui.selector import SelectItem, arrow_select
from torrent_finder.utils import start_esc_listener

_PAGE_MESSAGES = {
    "next": N_("next page: {number}"),
    "incomplete": N_("page incomplete; retry failed sources first"),
    "unavailable": N_("deeper retrieval unavailable"),
    "not_needed": N_("Auto not needed; no pages requested"),
    "exhausted": N_("exhausted for this query"),
    "limit": N_("page limit reached ({number})"),
}
_PAGE_HINTS = {
    "next": N_("next page {number}"), "incomplete": N_("retry first"),
    "unavailable": N_("no deeper pages"), "not_needed": N_("not needed"),
    "exhausted": N_("no more pages"), "limit": N_("page limit reached"),
}
_STATUS_WORDS = {
    "searching": N_("searching"), "pending": N_("not finished"), "auto": N_("auto, if needed"),
    "skipped": N_("not needed"), "results": N_("results"), "empty": N_("none"),
    "filtered": N_("filtered out"), "off": N_("off"), "timeout": N_("timed out"),
    "interrupted": N_("stopped"), "error": N_("failed"), "blocked": N_("blocked"),
    "missing_login": N_("login needed"), "rejected_login": N_("login rejected"), "login_error": N_("login failed"),
}
_LOGIN_WORDS = {"not set": N_("not set"), "set via environment": N_("set via environment"),
                "saved": N_("saved")}


def _pages(session):
    """Prefer structured states; support historical session-shaped callers.

    The snapshot harness and external callers can still supply page_status().
    Its compatibility contract is English regardless of interface language.
    """
    if hasattr(session, "page_states"):
        return session.page_states()
    pages = []
    for line in session.page_status():
        for status, message in _PAGE_MESSAGES.items():
            pattern = re.escape(message).replace(re.escape("{number}"), r"(\d+)")
            state = re.fullmatch(r"(.+?) / (.+?) · (.*): " + pattern, line)
            if state:
                provider, engine, query, *numbers = state.groups()
                pages.append(PageStatus(provider, engine, query, status, int(numbers[0]) if numbers else 0))
                break
    return tuple(pages)


def _word(status: str) -> str:
    word = _STATUS_WORDS.get(status, status.replace("_", " "))
    return t(word)


def _source_label(diagnostic, with_query: bool = False) -> Text:
    """``Movies & Series · Apibay``: the provider in steel, the engine in text colour (and the query)."""
    label = Text.assemble((f"{diagnostic.provider} · ", theme.MUTED), diagnostic.engine)
    if with_query:
        label.append(f" · {diagnostic.query}", style=theme.MUTED)
    return label


def _evidence(diagnostic, state_width: int = 0) -> Text:
    """The state word in its colour, padded to *state_width*, then what backs it: rows kept, time, retry."""
    word = _word(diagnostic.status)
    hint = Text.assemble((word + " " * max(0, state_width - cell_len(word)), status_style(diagnostic.status)))
    if diagnostic.status in {"results", "empty", "filtered"}:
        facts = t("{kept} of {raw} kept · {seconds:.1f} s", kept=diagnostic.kept,
                  raw=diagnostic.raw, seconds=diagnostic.seconds)
    elif diagnostic.status in {"off", "auto", "skipped", "pending"}:
        facts = ""
    else:
        facts = (t("{seconds:.1f} s · retryable", seconds=diagnostic.seconds) if diagnostic.retryable
                 else t("{seconds:.1f} s · not retryable", seconds=diagnostic.seconds))
    if facts:
        hint.append("  " + facts)
    return hint


def _failed(diagnostics) -> list:
    return [d for d in diagnostics if d.retryable or d.status == "blocked"]


def read_details(text, title=N_("Search details")):
    """Scroll complete evidence as rows so long errors fit tiny viewports."""
    lines = Text(text).wrap(console, max(12, console.size.width - 12))
    items = [SelectItem(line.plain or " ", passive=True) for line in lines]
    items.append(SelectItem(t("Back"), is_action=True))
    arrow_select(items, title=t(title), banner=_make_banner_panel(), footer=t("↑/↓ scroll • Esc back"))


def run_action(session, action):
    """Wait for the bounded coordinator to freeze a cancelled/partial action."""
    cancel, finish, done = threading.Event(), threading.Event(), threading.Event()
    out = {}

    def work():
        try:
            out["results"] = session.run(action, cancel_event=cancel, finish_event=finish)
        except Exception:
            out["error"] = t("Search action failed; earlier results are retained.")
        finally:
            done.set()

    threading.Thread(target=work, daemon=True).start()
    stop = start_esc_listener(cancel, finish_event=finish)
    try:
        label = (t("Retrying failed sources · Enter: results so far · Esc: stop") if action == "retry"
                 else t("Loading more results · Enter: results so far · Esc: stop"))
        with console.status(label, spinner=theme.SPINNER):
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
        return t("[warn]{failed} of {tried} failed[/warn]", failed=len(failed), tried=len(tried))
    return tn("{n} source answered", "{n} sources answered", len(tried))


def _page_item(page, with_query: bool = False) -> SelectItem:
    status = t(_PAGE_MESSAGES[page.status], number=page.number)
    short = t(_PAGE_HINTS[page.status], number=page.number)
    line = t("{provider} / {engine} · {query}: {status}", provider=page.provider,
             engine=page.engine, query=page.query, status=status)
    return SelectItem(_source_label(page, with_query), value=("pages", line), hint=short,
                      description=t("{status}\nEnter for full pagination status.", status=escape(status)))


def diagnostics_menu(session):
    from torrent_finder.credential_registry import CREDENTIAL_REGISTRY
    while True:
        failed = _failed(session.diagnostics)
        pages = _pages(session)
        items = [
            _section(t("Actions")),
            SelectItem(t("Retry failed sources"), value="retry", enabled=session.can_retry,
                       hint=", ".join(dict.fromkeys(d.engine for d in failed if d.retryable)),
                       description=t("Keep received results and retry failures. Required filters stay active.")),
            SelectItem(t("Load more results"), value="more", enabled=session.can_load_more,
                       hint=(tn("{n} source with more pages", "{n} sources with more pages", more)
                             if (more := sum(page.status == "next" for page in pages)) else ""),
                       description=t("One more page per supported source/query; up to 24 per action.")),
            SelectItem(t("Credentials / verify login"), value="credentials",
                       description=t("Saved credentials are not verified login. Open to verify or edit.")),
            SelectItem(t("Names searched ({count})", count=len(session.queries)), value=("names", "\n".join(session.queries)),
                       hint=" · ".join(session.queries),
                       description=t("Read the complete query list. Preset expansions appear on the individual source attempts.")),
        ]
        logins = [SelectItem(spec.name, passive=True, hint=t(_LOGIN_WORDS[login_status]) if login_status in _LOGIN_WORDS else login_status,
                             description=t("Configuration status only. Open Credentials to verify; search failures appear below."))
                  for spec in CREDENTIAL_REGISTRY for login_status in (spec.status(),)
                  if spec.id in {"rutracker", "madokami", "online_fix"} and any(
                      spec.name.casefold().replace("-", "") in d.engine.casefold().replace("-", "")
                      for d in session.diagnostics)]
        if logins:
            items += [_section(t("Logins")), *logins]
        if session.diagnostics:
            items.append(_section(t("Sources")))
            state_width = max(cell_len(_word(d.status)) for d in session.diagnostics)
            several = len(session.queries) > 1
            for d in session.diagnostics:
                items.append(SelectItem(_source_label(d, several), value=d, hint=_evidence(d, state_width),
                                        description=t("Query: {query}\nEnter for query, filters and errors.", query=escape(d.query))))
        if pages:
            items.append(_section(t("Pages")))
            items += [_page_item(line, len(session.queries) > 1) for line in pages]
        items.append(SelectItem(t("Back to results"), value=None, is_action=True))
        names = escape(", ".join(session.queries))
        idx = arrow_select(items, title=t("Search diagnostics › {names}", names=names) if names else t("Search diagnostics"),
                           status=diagnostics_status(session), banner=_make_banner_panel(),
                           footer=t("↑/↓ read • Enter action • Esc results"))
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
