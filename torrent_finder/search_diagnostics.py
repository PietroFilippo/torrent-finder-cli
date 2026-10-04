"""Per-attempt evidence, scoped to a search worker rather than global state."""

from contextvars import ContextVar
from dataclasses import dataclass, field

import requests

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
        failure = ("timeout", "Request timed out; this does not establish source availability.")
    elif isinstance(error, requests.RequestException):
        failure = ("error", "Network or HTTP request failed.")
    else:
        failure = ("error", message or "The source returned an unreadable response.")
    trace.failures.append(failure)


def record_interruption(timed_out):
    trace = _trace.get()
    if trace is not None:
        trace.failures.append(("timeout", "Source request budget expired.") if timed_out else
                              ("interrupted", "Stopped waiting; received rows are retained."))


def observe_response(response):
    trace = _trace.get()
    if trace is not None:
        code = getattr(response, "status_code", 200)
        if isinstance(code, int) and code >= 400:
            trace.failures.append(("error", f"Source returned HTTP {code}."))


def observe_request():
    trace = _trace.get()
    if trace is not None:
        trace.requests += 1


# Access problems are shown by their own message, without a provider prefix.
ACCESS_STATUSES = {"missing_login", "rejected_login", "login_error", "blocked"}


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
        counts = f"{self.raw} returned, {self.kept} kept before deduplication"
        removed = "; ".join(f"{name}: removed {count}" for name, count in self.removed)
        page = f"page {self.page}" if self.page else "initial search"
        requests = f"{self.requests} requests" if self.requests is not None else "request count unavailable"
        return "\n".join(filter(None, [
            f"{self.provider} / {self.engine} · {page} · attempt {self.attempt}",
            f"Query: {self.query}",
            f"{self.status.replace('_', ' ')} · {self.seconds:.1f}s · {requests}",
            counts, removed,
            "Active filters: " + self.filters if self.filters else "",
            f"{self.cached} cached rows; fetched times belong to the saved listing." if self.cached else "",
            self.message,
        ]))
