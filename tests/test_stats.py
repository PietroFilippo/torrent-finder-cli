"""Runtime totals survive saving and reopening, while counters stay integers."""

import json
import unittest

import isolation  # noqa: F401
from isolation import isolate_store, restart_store
from torrent_finder import stats, store


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.path = isolate_store(self)

    def test_runtime_accumulates_across_saved_sessions(self):
        stats.add_runtime_seconds(12.5)
        store.flush()
        restart_store()
        stats.add_runtime_seconds(7.25)
        store.flush()
        restart_store()
        self.assertEqual(stats.get_all_stats()["total_runtime_s"], 19.75)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["stats"]["total_runtime_s"], 19.75)

    def test_runtime_accepts_only_finite_numbers_and_counters_only_integers(self):
        for current, runtime, count in ((10, 10.5, 11), (10.25, 10.75, 1), (True, 0.5, 1),
                                        (float("nan"), 0.5, 1), (float("inf"), 0.5, 1),
                                        (float("-inf"), 0.5, 1), ("10", 0.5, 1), (None, 0.5, 1)):
            with self.subTest(current=current):
                data = {"total_runtime_s": current, "session_count": current}
                stats._bump(data, "total_runtime_s", by=0.5)
                stats._bump(data, "session_count")
                self.assertEqual(data, {"total_runtime_s": runtime, "session_count": count})

    def test_invalid_runtime_increments_do_not_poison_the_saved_total(self):
        stats.add_runtime_seconds(10.25)
        for seconds in (float("nan"), float("inf"), float("-inf"), True, 0, -1):
            stats.add_runtime_seconds(seconds)
        store.flush()
        restart_store()
        self.assertEqual(stats.get_all_stats()["total_runtime_s"], 10.25)


if __name__ == "__main__":
    unittest.main()
