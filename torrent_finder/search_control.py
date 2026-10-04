"""Cooperative deadlines for search sessions, scoped to their worker threads.

Calls outside a search session retain their own timeouts. An already-running
request cannot be forcibly killed, but no retries start after its budget expires.
"""

from contextvars import ContextVar
from dataclasses import dataclass
import threading
import time

import requests


_ENGINE_SECONDS = 12.0
_MIN_REQUEST_SECONDS = 2.0  # a pause must leave at least this long for the request after it
_request_budget = ContextVar("search_request_budget", default=None)


class SearchInterrupted(Exception):
    pass


@dataclass
class _RequestBudget:
    control: "SearchControl"
    deadline: float
    timed_out: bool = False


def search_request(send, *args, **kwargs):
    """Call a requests function with the current search's remaining time."""
    from torrent_finder.search_diagnostics import observe_request, observe_response, record_failure, record_interruption
    budget = _request_budget.get()
    if budget is not None:
        remaining = budget.deadline - time.monotonic()
        if budget.control.stopped() or remaining <= 0:
            record_interruption(remaining <= 0)
            raise SearchInterrupted()
        original = kwargs.get("timeout", 6)
        connect, read = original if isinstance(original, tuple) else (original, original)
        kwargs["timeout"] = (
            min(connect or 3, 3, remaining / 2),
            min(read or 6, 6, remaining / 2),
        )
    try:
        observe_request()
        response = send(*args, **kwargs)
        observe_response(response)
        return response
    except requests.RequestException as error:
        record_failure(error)
        if budget is not None and isinstance(error, requests.Timeout):
            budget.timed_out = True
        raise


def search_stopped() -> bool:
    """True when the current search was cancelled, finished early or ran out of time."""
    budget = _request_budget.get()
    return budget is not None and (budget.control.stopped() or time.monotonic() >= budget.deadline)


def search_wait(seconds: float) -> bool:
    """Pause the current engine for *seconds* (e.g. a source's required spacing).

    Inside a search session, returns False without pausing when the pause plus
    a request would not fit in the engine's remaining time, and raises
    ``SearchInterrupted`` if the search is cancelled or finished meanwhile.
    Outside a session it simply sleeps.
    """
    budget = _request_budget.get()
    if budget is None:
        time.sleep(seconds)
        return True
    end = time.monotonic() + seconds
    if end + _MIN_REQUEST_SECONDS > budget.deadline:
        return False
    while (left := end - time.monotonic()) > 0:
        if budget.control.stopped():
            raise SearchInterrupted()
        time.sleep(min(0.1, left))
    return True


class Cooldown:
    """A source's request to slow down (HTTP 429 with optional Retry-After),
    honoured by every search in the app until it has passed."""

    DEFAULT_SECONDS = 60.0
    MAX_SECONDS = 900.0

    def __init__(self, name: str) -> None:
        self.name = name
        self.until = 0.0
        self._lock = threading.Lock()

    def check(self) -> None:
        """Raise ``SearchError`` instead of asking the source again too soon."""
        with self._lock:
            remaining = self.until - time.monotonic()
        if remaining > 0:
            from torrent_finder.search_errors import SearchError
            raise SearchError(f"{self.name} asked the app to slow down; it is searched again in "
                              f"{max(1, round(remaining))} s.")

    def note(self, response) -> None:
        """Start the cooldown when *response* is a rate limit, then raise via ``check``."""
        if getattr(response, "status_code", 200) != 429:
            return
        seconds = _retry_after_seconds(getattr(response, "headers", {}).get("Retry-After"))
        with self._lock:
            self.until = time.monotonic() + min(self.MAX_SECONDS, max(1.0, seconds))
        self.check()


def _retry_after_seconds(value) -> float:
    """Seconds from a Retry-After header (delay or HTTP date); the default when absent."""
    if not value:
        return Cooldown.DEFAULT_SECONDS
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    try:
        from datetime import datetime, timezone
        from email.utils import parsedate_to_datetime
        return (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
    except (TypeError, ValueError, IndexError):
        return Cooldown.DEFAULT_SECONDS


class SharedResults:
    """Rows of one source, shared between searches of the same query.

    Both game providers search FitGirl and Online-Fix: an identical query asked
    again within *seconds* reuses the rows, and a concurrent identical search
    waits for the first instead of sending its own requests. A search that
    raises or records a failure (an HTTP error, a missing second page) is not
    remembered, so a retry asks the source again.
    """

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self._lock = threading.Lock()
        self._keys: dict[str, threading.Lock] = {}
        self._recent: dict[str, tuple[float, list]] = {}

    def run(self, query: str, search):
        key = " ".join(query.casefold().split())
        with self._lock:
            key_lock = self._keys.setdefault(key, threading.Lock())
        while not key_lock.acquire(timeout=0.1):
            if search_stopped():
                raise SearchInterrupted()
        try:
            reused = self._recent.get(key)
            if reused and time.monotonic() - reused[0] < self.seconds:
                return list(reused[1])
            from torrent_finder.search_diagnostics import failure_mark
            mark = failure_mark()
            rows = search(query)
            if failure_mark() > mark:
                return list(rows)  # incomplete: shown, but not reused
            now = time.monotonic()
            self._recent = {k: v for k, v in self._recent.items() if now - v[0] < self.seconds}
            self._recent[key] = (now, list(rows))
            return list(rows)
        finally:
            key_lock.release()


class SearchControl:
    def __init__(self, seconds, cancel_event=None, finish_event=None):
        self.deadline = time.monotonic() + seconds
        self.cancel = cancel_event or threading.Event()
        self.finish = finish_event or threading.Event()
        self._lock = threading.Lock()
        self._timeouts = set()

    def stopped(self):
        return self.cancel.is_set() or self.finish.is_set() or time.monotonic() >= self.deadline

    def timeouts(self):
        with self._lock:
            return set(self._timeouts)

    def run_engine(self, provider_slug, engine_name, operation, slots):
        """Run one engine search within its budget. A search stopped before it
        started raises ``SearchInterrupted``: it is unanswered, not empty."""
        while not self.stopped():
            if slots.acquire(timeout=0.05):
                break
        else:
            raise SearchInterrupted()
        budget = _RequestBudget(self, min(self.deadline, time.monotonic() + _ENGINE_SECONDS))
        token = _request_budget.set(budget)
        try:
            if self.stopped():
                raise SearchInterrupted()
            return operation()
        finally:
            _request_budget.reset(token)
            slots.release()
            if budget.timed_out or (time.monotonic() >= budget.deadline and not self.stopped()):
                with self._lock:
                    self._timeouts.add((provider_slug, engine_name))
