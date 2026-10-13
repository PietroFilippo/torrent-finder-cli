"""After a batch handoff with failures, the finished prompt offers to run only the failed and unprocessed items again."""

import threading
import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirects saved settings before anything reads them

from torrent_finder import acquisition, main
from torrent_finder.acquisition import BatchItemOutcome
from torrent_finder.ui import prompts
from torrent_finder.ui.selector import SelectItem

PROVIDER = SimpleNamespace(slug="movies", name="Movies & Series")


def results(count: int) -> list[dict]:
    return [dict(name=f"Title {i}", info_hash=chr(97 + i) * 40, seeders=5, source="Apibay") for i in range(count)]


class FakeAdapter:
    """Hands items over by name: those in *failing* fail; *stop_at* trips the Esc event when reached."""

    has_magnet = True

    def __init__(self, failing=(), stop_at=None, log=None):
        self.failing, self.stop_at, self.log = set(failing), stop_at, log if log is not None else []

    def batch_item(self, result, *, download_dir, cancel_event, set_status):
        self.log.append(result["name"])
        if result["name"] == self.stop_at:
            self.stop_at = None  # Esc once; the retry runs through
            cancel_event.set()
            return None
        return BatchItemOutcome(ok=result["name"] not in self.failing)


class RetryRowTests(unittest.TestCase):
    def rows(self, **kwargs):
        captured = {}
        with patch.object(prompts, "arrow_select", side_effect=lambda items, **kw: captured.update(items=items) or None):
            prompts.download_complete_prompt("Batch handoff finished", **kwargs)
        return captured["items"]

    def test_the_retry_row_appears_only_when_asked_for(self):
        self.assertEqual([item.value for item in self.rows(summary="x")], ["next", "back"])
        items = self.rows(summary="Couldn't open 2: a, b", retry="Retry the 2 that failed")
        self.assertEqual([item.value for item in items], ["next", "retry", "back"])
        self.assertEqual(items[1].label, "Retry the 2 that failed")
        self.assertIn("Runs only those again", items[1].description)
        self.assertIn("Couldn't open 2", items[1].description)

    def test_choosing_it_returns_retry(self):
        with patch.object(prompts, "arrow_select", side_effect=lambda items, **kw: next(
                i for i, item in enumerate(items) if item.value == "retry")):
            self.assertEqual(prompts.download_complete_prompt("Done", retry="Retry the 1 that failed"), "retry")


class HandoffRetryTests(unittest.TestCase):
    def run_handoff(self, adapter, prompt_answers, idxs=(0, 1, 2, 3)):
        prompts_seen = []

        def prompt(message, *, summary="", retry=""):
            prompts_seen.append((summary, retry))
            return prompt_answers.pop(0)

        with patch.object(acquisition, "for_result", return_value=adapter), \
             patch.object(acquisition, "batch_download_dir", return_value=""), \
             patch.object(main, "download_complete_prompt", side_effect=prompt), \
             patch.object(main, "start_esc_listener", return_value=threading.Event()), \
             patch.object(main, "record_torrent_picked"), patch.object(main, "record_magnet_dispatch"), \
             patch.object(main, "provider_for_result", return_value=PROVIDER), \
             patch.object(main.console, "status", lambda *a, **k: _NoStatus()):
            outcome = main._batch_handoff(PROVIDER, results(4), list(idxs))
        return outcome, prompts_seen, adapter.log

    def test_a_partial_failure_offers_the_failed_ones_and_retries_only_them(self):
        adapter = FakeAdapter(failing={"Title 1", "Title 3"})
        outcome, seen, log = self.run_handoff(adapter, ["retry", "next"])
        self.assertEqual(outcome, "next")
        self.assertEqual(seen[0][1], "Retry the 2 that failed")
        self.assertIn("Couldn't open 2", seen[0][0])
        self.assertEqual(log, ["Title 0", "Title 1", "Title 2", "Title 3", "Title 1", "Title 3"])
        self.assertEqual(seen[1][1], "")  # the second pass failed outright: no partial failure, no retry row
        self.assertEqual(len(seen), 2)

    def test_a_retry_that_succeeds_offers_nothing_more(self):
        adapter = FakeAdapter(failing={"Title 2"})
        answers = ["retry", "next"]

        def prompt(message, *, summary="", retry=""):
            adapter.failing.clear()  # the client is back for the second pass
            return answers.pop(0)
        with patch.object(acquisition, "for_result", return_value=adapter), \
             patch.object(acquisition, "batch_download_dir", return_value=""), \
             patch.object(main, "download_complete_prompt", side_effect=prompt) as seen, \
             patch.object(main, "start_esc_listener", return_value=threading.Event()), \
             patch.object(main, "record_torrent_picked"), patch.object(main, "record_magnet_dispatch"), \
             patch.object(main, "provider_for_result", return_value=PROVIDER), \
             patch.object(main.console, "status", lambda *a, **k: _NoStatus()):
            self.assertEqual(main._batch_handoff(PROVIDER, results(4), [0, 1, 2, 3]), "next")
        self.assertEqual(seen.call_args_list[1].kwargs["retry"], "")
        self.assertEqual(adapter.log, ["Title 0", "Title 1", "Title 2", "Title 3", "Title 2"])

    def test_a_stopped_run_offers_the_unprocessed_items(self):
        adapter = FakeAdapter(stop_at="Title 2")
        outcome, seen, log = self.run_handoff(adapter, ["retry", "back"])
        self.assertEqual(outcome, "back")
        self.assertEqual(seen[0][1], "Continue with the 2 left")
        self.assertIn("Stopped after 2 of 4", seen[0][0])
        self.assertEqual(log[-2:], ["Title 2", "Title 3"])  # the aborted item runs again, then the rest

    def test_everything_sent_or_everything_failed_offers_no_retry(self):
        outcome, seen, _ = self.run_handoff(FakeAdapter(), ["next"])
        self.assertEqual((outcome, seen[0][1]), ("next", ""))
        outcome, seen, _ = self.run_handoff(FakeAdapter(failing={f"Title {i}" for i in range(4)}), ["back"])
        self.assertEqual((outcome, seen[0][1]), ("back", ""))

    def test_back_keeps_the_whole_selection_for_the_batch_menu(self):
        adapter = FakeAdapter(failing={"Title 1"})
        outcome, seen, log = self.run_handoff(adapter, ["back"])
        self.assertEqual(outcome, "back")
        self.assertEqual(len(log), 4)  # nothing re-run: the batch menu's "Open all" runs all again


class _NoStatus:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def update(self, *args, **kwargs):
        pass


if __name__ == "__main__":
    unittest.main()
