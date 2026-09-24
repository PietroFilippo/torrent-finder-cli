"""Cooperative deadlines for combined searches, scoped to their worker threads.

Normal searches and downloads retain their own timeouts. An already-running
request cannot be forcibly killed, but no retries start after its budget expires.
"""

from contextvars import ContextVar
from dataclasses import dataclass
import threading
import time

import requests


_ENGINE_SECONDS = 12.0
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
    budget = _request_budget.get()
    if budget is None:
        return send(*args, **kwargs)
    remaining = budget.deadline - time.monotonic()
    if budget.control.stopped() or remaining <= 0:
        raise SearchInterrupted()
    original = kwargs.get("timeout", 6)
    connect, read = original if isinstance(original, tuple) else (original, original)
    kwargs["timeout"] = (
        min(connect or 3, 3, remaining / 2),
        min(read or 6, 6, remaining / 2),
    )
    try:
        return send(*args, **kwargs)
    except requests.Timeout:
        budget.timed_out = True
        raise


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
        while not self.stopped():
            if slots.acquire(timeout=0.05):
                break
        else:
            return []
        budget = _RequestBudget(self, min(self.deadline, time.monotonic() + _ENGINE_SECONDS))
        token = _request_budget.set(budget)
        try:
            if self.stopped():
                return []
            return operation()
        finally:
            _request_budget.reset(token)
            slots.release()
            if budget.timed_out or (time.monotonic() >= budget.deadline and not self.stopped()):
                with self._lock:
                    self._timeouts.add((provider_slug, engine_name))
