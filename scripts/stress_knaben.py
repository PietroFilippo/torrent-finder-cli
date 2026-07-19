"""Sequential live smoke/stress matrix for the Knaben API adapter."""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from torrent_finder.providers.book_provider import BookProvider
from torrent_finder.providers.game_provider import GameProvider
from torrent_finder.providers.movie_provider import MovieProvider


CASES = (
    (MovieProvider, "finding nemo"),
    (MovieProvider, "spirited away"),
    (MovieProvider, "fantastic mr. fox"),
    (BookProvider, "Metamorphosis"),
    (BookProvider, "the hobbit"),
    (GameProvider, "elden ring"),
    (GameProvider, "hollow knight"),
)


@dataclass
class Observation:
    rows: int
    seconds: float


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run category-scoped Knaben searches sequentially and report "
            "success rate, latency, and originating trackers."
        )
    )
    parser.add_argument("--rounds", type=_positive_int, default=1)
    parser.add_argument(
        "--delay",
        type=float,
        default=0.75,
        help="seconds between searches (default: 0.75)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit nonzero if any query returns no usable info hashes",
    )
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("--delay cannot be negative")

    observations: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    for round_number in range(1, args.rounds + 1):
        print(f"round {round_number}/{args.rounds}")
        for provider_type, query in CASES:
            provider = provider_type()
            started = time.perf_counter()
            results = provider._search_knaben(query)
            elapsed = time.perf_counter() - started
            observations[(provider.slug, query)].append(
                Observation(len(results), elapsed)
            )
            origins = Counter(
                result.get("knaben_tracker") or "unknown"
                for result in results
            )
            origin_summary = ", ".join(
                f"{name}:{count}" for name, count in origins.most_common(3)
            )
            count = str(len(results)) if results else "FAIL"
            print(
                f"  {provider.slug:8} {query!r:22} -> {count:>4}  "
                f"{elapsed:5.2f}s  {origin_summary}"
            )
            if args.delay:
                time.sleep(args.delay)

    print("summary")
    had_failure = False
    for (slug, query), values in observations.items():
        successes = sum(value.rows > 0 for value in values)
        had_failure |= successes != len(values)
        print(
            f"  {slug:8} {query!r:22} "
            f"success={successes}/{len(values)}  "
            f"median={statistics.median(v.seconds for v in values):.2f}s"
        )
    return 1 if args.strict and had_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
