"""Per-attempt evidence, scoped to a search worker rather than global state."""

# i18n: converted
from contextvars import ContextVar
from dataclasses import dataclass, field

import requests

from torrent_finder.i18n import N_, t, tn

_trace = ContextVar("search_diagnostic_trace", default=None)


@dataclass
class RequestTrace:
    failures: list[tuple[str, str]] = field(default_factory=list)
    requests: int = 0

    def __enter__(self):
        self.token = _trace.set(self)
        return self

    def __exit__(self, *_args):
        _trace.reset(self.token)


def failure_mark() -> int:
    """How many failures the current search has recorded (see forget_failures)."""
    trace = _trace.get()
    return len(trace.failures) if trace is not None else 0


def forget_failures(mark: int) -> None:
    """Drop failures recorded since *mark*: a later attempt (another mirror) answered."""
    trace = _trace.get()
    if trace is not None:
        del trace.failures[mark:]


def record_failure(error=None, *, message=""):
    trace = _trace.get()
    if trace is None:
        return
    if type(error).__name__ == "SearchInterrupted":
        return  # search_request already recorded the reason before unwinding
    # Never expose exception URLs, request bodies, headers, or credentials.
    if isinstance(error, requests.Timeout):
        failure = ("timeout", t("Request timed out; this does not establish source availability."))
    elif isinstance(error, requests.RequestException):
        failure = ("error", t("Network or HTTP request failed."))
    else:
        failure = ("error", message or t("The source returned an unreadable response."))
    trace.failures.append(failure)


def record_interruption(timed_out):
    trace = _trace.get()
    if trace is not None:
        trace.failures.append(("timeout", t("Source request budget expired.")) if timed_out else
                              ("interrupted", t("Stopped waiting; received rows are retained.")))


def observe_response(response):
    trace = _trace.get()
    if trace is not None:
        code = getattr(response, "status_code", 200)
        if isinstance(code, int) and code >= 400:
            trace.failures.append(("error", t("Source returned HTTP {code}.", code=code)))


def observe_request():
    trace = _trace.get()
    if trace is not None:
        trace.requests += 1


# Access problems are shown by their own message, without a provider prefix.
ACCESS_STATUSES = {"missing_login", "rejected_login", "login_error", "blocked"}

# Mark the historical code-to-word display; status codes themselves remain identities.
_STATUS_LABELS = {
    "pending": N_("pending"), "searching": N_("searching"), "results": N_("results"),
    "empty": N_("empty"), "filtered": N_("filtered"), "off": N_("off"), "auto": N_("auto"),
    "skipped": N_("skipped"), "timeout": N_("timeout"), "interrupted": N_("interrupted"),
    "error": N_("error"), "blocked": N_("blocked"), "missing_login": N_("missing login"),
    "rejected_login": N_("rejected login"), "login_error": N_("login error"),
}


def status_label(status: str) -> str:
    return t(_STATUS_LABELS[status]) if status in _STATUS_LABELS else status.replace("_", " ")


@dataclass(frozen=True)
class Diagnostic:
    provider: str
    engine: str
    query: str
    page: int
    status: str
    raw: int = 0
    kept: int = 0
    removed: tuple[tuple[str, int], ...] = ()
    seconds: float = 0
    message: str = ""
    attempt: int = 0
    cached: int = 0
    requests: int | None = 0
    filters: str = ""
    hint: str = ""  # the engine's advice for an empty result

    @property
    def retryable(self):
        # "blocked" (an anti-bot check) is left out: retrying right away can't pass it.
        return self.status in {"error", "timeout", "interrupted", "missing_login", "rejected_login", "login_error"}

    def describe(self):
        counts = t("{raw} returned, {kept} kept before deduplication", raw=self.raw, kept=self.kept)
        removed = "; ".join(t("{name}: removed {count}", name=t(name), count=count) for name, count in self.removed)
        page = t("page {number}", number=self.page) if self.page else t("initial search")
        # English retains its historical count wording; Portuguese has distinct plural forms.
        requests = tn("{n} requests", "{n} requests", self.requests) if self.requests is not None else t("request count unavailable")
        return "\n".join(filter(None, [
            t("{provider} / {engine} · {page} · attempt {attempt}", provider=self.provider,
              engine=self.engine, page=page, attempt=self.attempt),
            t("Query: {query}", query=self.query),
            t("{status} · {seconds:.1f}s · {requests}", status=status_label(self.status), seconds=self.seconds, requests=requests),
            counts, removed,
            t("Active filters: {filters}", filters=self.filters) if self.filters else "",
            tn("{n} cached rows; fetched times belong to the saved listing.",
               "{n} cached rows; fetched times belong to the saved listing.", self.cached) if self.cached else "",
            self.message,
        ]))
