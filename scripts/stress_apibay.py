"""Sequential live stress test for APIBay's volatile search endpoint."""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import requests

# Allow the documented direct command to work before an editable install.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from torrent_finder.constants import API_URL
from torrent_finder.providers.book_provider import BookProvider
from torrent_finder.providers.game_provider import GameProvider
from torrent_finder.providers.movie_provider import MovieProvider


CASES = (
    (MovieProvider, "finding nemo"),
    (MovieProvider, "FINDING NEMO"),
    (MovieProvider, "spirited away"),
    (MovieProvider, "fantastic mr. fox"),
    (MovieProvider, "the matrix"),
    (BookProvider, "Metamorphosis"),
    (BookProvider, "the hobbit"),
    (GameProvider, "elden ring"),
    (GameProvider, "hollow knight"),
)


@dataclass
class Observation:
    rows: int
    requests: int
    seconds: float
    cached: bool


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the APIBay regression matrix sequentially and report success "
            "rate, request amplification, and latency."
        )
    )
    parser.add_argument("--rounds", type=_positive_int, default=1)
    parser.add_argument(
        "--delay",
        type=float,
        default=0.25,
        help="seconds between searches (default: 0.25)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit nonzero if any query returns no APIBay rows",
    )
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("--delay cannot be negative")

    original_get = requests.get
    request_count = 0

    def counting_get(url, *call_args, **call_kwargs):
        nonlocal request_count
        if url == API_URL:
            request_count += 1
        return original_get(url, *call_args, **call_kwargs)

    requests.get = counting_get
    observations: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    try:
        for round_number in range(1, args.rounds + 1):
            print(f"round {round_number}/{args.rounds}")
            for provider_type, query in CASES:
                provider = provider_type()
                before = request_count
                started = time.perf_counter()
                results = provider._search_apibay(query)
                elapsed = time.perf_counter() - started
                used_requests = request_count - before
                cached = any(
                    bool(result.get("apibay_cached_at")) for result in results
                )
                key = (provider.slug, query)
                observations[key].append(
                    Observation(len(results), used_requests, elapsed, cached)
                )
                count = (
                    f"{len(results)}*" if cached
                    else str(len(results)) if results
                    else "FAIL"
                )
                print(
                    f"  {provider.slug:8} {query!r:22} -> {count:>5}  "
                    f"requests={used_requests:2}  {elapsed:5.2f}s"
                )
                if args.delay:
                    time.sleep(args.delay)
    finally:
        requests.get = original_get

    print("summary")
    had_failure = False
    for (slug, query), values in observations.items():
        successes = sum(value.rows > 0 for value in values)
        cached_hits = sum(value.cached for value in values)
        had_failure |= successes != len(values)
        request_values = [value.requests for value in values]
        timing_values = [value.seconds for value in values]
        print(
            f"  {slug:8} {query!r:22} "
            f"success={successes}/{len(values)}  "
            f"cached={cached_hits}/{len(values)}  "
            f"requests={min(request_values)}-{max(request_values)}  "
            f"median={statistics.median(timing_values):.2f}s"
        )
    return 1 if args.strict and had_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
