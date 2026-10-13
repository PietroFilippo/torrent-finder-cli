"""Idle watcher ticks must not measure an unchanged list or redraw it."""

import io
import threading
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import isolation  # noqa: F401
from rich.console import Console

from torrent_finder import i18n
from torrent_finder.ui import selector, table, theme
from torrent_finder.ui.selector import SelectItem


class SelectorIdleTests(unittest.TestCase):
    def run_selector(self, items, read, **kwargs):
        screen = Console(file=io.StringIO(), width=235, height=60)
        stop = threading.Event()
        worker = Mock()
        clock = [0.0]

        def thread(*, target: object, **_):
            worker.target = target
            return worker

        def ticks(count=60, change=None):
            def wait(_):
                clock[0] += 0.05
                if change:
                    change()
                return False
            remaining = [count]

            def step(_):
                if not remaining[0]:
                    return True
                remaining[0] -= 1
                return wait(0)
            with patch.object(stop, "wait", side_effect=step):
                worker.target()

        with ExitStack() as stack:
            stack.enter_context(patch.object(selector, "console", screen))
            stack.enter_context(patch.object(selector.threading, "Event", return_value=stop))
            stack.enter_context(patch.object(selector.threading, "Thread", side_effect=thread))
            stack.enter_context(patch.object(selector.time, "monotonic", side_effect=lambda: clock[0]))
            stack.enter_context(patch.object(selector.display, "enter_screen"))
            stack.enter_context(patch.object(selector.display, "leave_screen"))
            geometry = stack.enter_context(patch.object(selector, "_geometry", wraps=selector._geometry))
            panel = stack.enter_context(patch.object(selector, "_build_panel", wraps=selector._build_panel))
            render = stack.enter_context(patch.object(selector, "_render", return_value=True))
            stack.enter_context(patch.object(selector.readchar, "readkey",
                                             side_effect=lambda: read(screen, ticks, geometry, render, panel)))
            return selector.arrow_select(items, **kwargs)

    def test_idle_ticks_reuse_geometry_until_cursor_resize_or_density_changes(self):
        turns = iter(range(3))

        def read(screen, ticks, geometry, render, panel):
            turn = next(turns)
            if turn == 0:
                ticks()
                self.assertEqual(geometry.call_count, 1)
                self.assertEqual(render.call_count, 1)
                return selector.readchar.key.DOWN
            if turn == 1:
                ticks()
                self.assertEqual(geometry.call_count, 2)
                screen.width = 120
                ticks()
                self.assertEqual(geometry.call_count, 3)
                self.assertEqual(render.call_count, 3)
                theme.apply(density="compact")
                ticks()
                self.assertEqual(geometry.call_count, 4)
                self.assertEqual(render.call_count, 4)
                return selector.readchar.key.UP
            ticks()
            self.assertEqual(geometry.call_count, 5)
            return selector.readchar.key.ESC

        self.run_selector([SelectItem(f"Row {i}", hint="today") for i in range(2000)], read)

    def test_marquee_advances_without_recomputing_geometry(self):
        def read(screen, ticks, geometry, render, panel):
            ticks()
            self.assertEqual(geometry.call_count, 1)
            drawn_ticks = [call.kwargs["tick"] for call in panel.call_args_list]
            self.assertEqual(drawn_ticks[0], 0)
            self.assertGreater(drawn_ticks[-1], 8)
            self.assertEqual(drawn_ticks, sorted(set(drawn_ticks)))
            return selector.readchar.key.ESC

        self.run_selector([SelectItem("Long label " * 50)] +
                          [SelectItem(f"Row {i}") for i in range(2000)], read)

    def test_live_refresh_invalidates_geometry_even_for_an_in_place_edit(self):
        items = [SelectItem("Short")]
        calls = [0]

        def refresh():
            calls[0] += 1
            if calls[0] == 8:
                items[0].label = "Long label " * 50
                items[0].description = "Inspector help"
                return True
            return False

        def read(screen, ticks, geometry, render, panel):
            ticks()
            self.assertEqual(geometry.call_count, 2)
            self.assertGreater(render.call_count, 2)
            self.assertGreater(panel.call_args.kwargs["tick"], 0)
            return selector.readchar.key.ESC

        self.run_selector(items, read, refresh=refresh)

    def test_action_callback_invalidates_in_place_label_and_hint_edits(self):
        turns = iter(range(2))
        items = [SelectItem("Before", hint="old")]

        def action(cursor, rows):
            rows[0].label = "After"
            rows[0].hint = "new hint"
            rows[0].marker = "*"

        def read(screen, ticks, geometry, render, panel):
            if next(turns) == 0:
                ticks()
                self.assertEqual(geometry.call_count, 1)
                return "x"
            ticks()
            self.assertEqual(geometry.call_count, 2)
            return selector.readchar.key.ESC

        self.run_selector(items, read, key_actions={"x": action})

    def test_focus_change_restarts_dwell_and_short_row_stops_marquee(self):
        turns = iter(range(3))

        def read(screen, ticks, geometry, render, panel):
            turn = next(turns)
            if turn == 0:
                ticks()
                self.assertGreater(panel.call_args.kwargs["tick"], 0)
                return selector.readchar.key.DOWN
            self.assertEqual(panel.call_args.kwargs["tick"], 0)
            rendered = render.call_count
            ticks(10)  # half the dwell: no frame should be repainted
            self.assertEqual(render.call_count, rendered)
            ticks()
            if turn == 1:
                self.assertGreater(panel.call_args.kwargs["tick"], 0)
                return selector.readchar.key.DOWN
            self.assertEqual(render.call_count, rendered)  # short row stays idle
            self.assertEqual(geometry.call_count, 3)
            return selector.readchar.key.ESC

        self.run_selector([SelectItem("Long label " * 50), SelectItem("Another label " * 50),
                           SelectItem("Short")], read)

    def test_item_append_and_language_change_invalidate_cached_geometry(self):
        items = [SelectItem("Short")]

        def read(screen, ticks, geometry, render, panel):
            ticks()
            self.assertEqual(geometry.call_count, 1)
            items.append(SelectItem("Added", description="Inspector details"))
            ticks()
            self.assertEqual(geometry.call_count, 2)
            self.assertGreater(panel.call_args.kwargs["measurement"].pane_width, 0)
            i18n.use("pt-BR")
            ticks()
            self.assertEqual(geometry.call_count, 3)
            self.assertEqual(render.call_count, 3)
            return selector.readchar.key.ESC

        self.run_selector(items, read)

    def test_download_revision_redraws_once_then_returns_to_idle(self):
        from torrent_finder.ui import downloads

        def read(screen, ticks, geometry, render, panel):
            ticks()
            self.assertEqual(geometry.call_count, 1)
            manager.revision += 1
            ticks()
            self.assertEqual(geometry.call_count, 2)
            self.assertEqual(render.call_count, 2)
            return selector.readchar.key.ESC

        manager = Mock(revision=1)
        manager.snapshot.return_value = []
        with patch.object(downloads, "current", return_value=manager):
            self.run_selector([SelectItem("Short")], read)


class ResultIdleTests(unittest.TestCase):
    def test_focused_result_marquee_refreshes_without_recounting_sources(self):
        rows = [{"name": "Long title " * 50, "source": "Nyaa", "info_hash": "a" * 40,
                 "seeders": 10, "leechers": 1, "size": 1024}]
        screen = Console(file=io.StringIO(), width=120, height=40)
        stop = threading.Event()
        worker = Mock()
        clock = [0.0]
        live = Mock()
        live.__enter__ = Mock(return_value=live)
        live.__exit__ = Mock(return_value=False)

        def thread(*, target, **_):
            worker.target = target
            return worker

        def read():
            def wait(_):
                clock[0] += table._TICK_INTERVAL_S
                return clock[0] > 3.0

            with patch.object(stop, "wait", side_effect=wait):
                worker.target()
            self.assertEqual(counts.call_count, 1)
            self.assertGreater(live.update.call_count, 1)
            self.assertTrue(all(call.kwargs["refresh"] for call in live.update.call_args_list))
            drawn_ticks = [call.kwargs["tick"] for call in build.call_args_list]
            self.assertEqual(drawn_ticks[0], 0)
            self.assertGreater(drawn_ticks[-1], 8)
            self.assertEqual(drawn_ticks, sorted(set(drawn_ticks)))
            return table.readchar.key.ESC

        with patch.object(table, "console", screen), \
             patch.object(table, "Live", return_value=live), \
             patch.object(table.threading, "Event", return_value=stop), \
             patch.object(table.threading, "Thread", side_effect=thread), \
             patch.object(table.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(table, "build_table", wraps=table.build_table) as build, \
             patch.object(table, "_source_counts", wraps=table._source_counts) as counts, \
             patch.object(table.readchar, "readkey", side_effect=read):
            table.interactive_select(rows)

    def test_idle_ticker_measures_once_and_resize_remeasures_without_recounting(self):
        rows = [{"name": f"Row {i}", "source": "Nyaa", "info_hash": f"{i:040x}",
                 "seeders": 10, "leechers": 1, "size": 1024} for i in range(2000)]
        screen = Console(file=io.StringIO(), width=235, height=60)
        stop = threading.Event()
        worker = Mock()
        live = Mock()
        live.__enter__ = Mock(return_value=live)
        live.__exit__ = Mock(return_value=False)

        def thread(*, target, **_):
            worker.target = target
            return worker

        def read():
            layout.reset_mock()  # initial frame has already been measured
            step = 0
            resized_calls = 0

            def wait(_):
                nonlocal step, resized_calls
                step += 1
                if step == 40:
                    self.assertEqual(layout.call_count, 1)
                    live.update.assert_not_called()
                    screen.width = 120
                if step == 41:
                    resized_calls = layout.call_count
                    self.assertGreater(resized_calls, 1)
                    live.update.assert_called_once()
                    self.assertTrue(live.update.call_args.kwargs["refresh"])
                if step == 80:
                    self.assertEqual(layout.call_count, resized_calls)
                    self.assertEqual(counts.call_count, 1)
                    return True
                return False

            with patch.object(stop, "wait", side_effect=wait):
                worker.target()
            return table.readchar.key.ESC

        with patch.object(table, "console", screen), \
             patch.object(table, "Live", return_value=live) as live_class, \
             patch.object(table.threading, "Event", return_value=stop), \
             patch.object(table.threading, "Thread", side_effect=thread), \
             patch.object(table, "_page_layout", wraps=table._page_layout) as layout, \
             patch.object(table, "_source_counts", wraps=table._source_counts) as counts, \
             patch.object(table.readchar, "readkey", side_effect=read):
            table.interactive_select(rows)
        self.assertFalse(live_class.call_args.kwargs["auto_refresh"])


class ResultCountsTests(unittest.TestCase):
    def test_source_counts_are_reused_on_cursor_checkbox_and_inspector_redraws(self):
        rows = [{"name": f"Row {i}", "source": "Nyaa", "info_hash": f"{i:040x}",
                 "seeders": 10, "leechers": 1, "size": 1024} for i in range(200)]
        screen = Console(file=io.StringIO(), width=235, height=60)
        with patch.object(table, "console", screen), \
             patch.object(table.readchar, "readkey", side_effect=[table.readchar.key.DOWN, " ", "i", "a", "\x1b"]), \
             patch.object(table, "_source_counts", wraps=table._source_counts) as counts:
            table.interactive_select(rows)
        self.assertEqual(counts.call_count, 1)

    def test_refinement_recounts_sources_for_the_new_view(self):
        rows = [{"name": name, "source": source, "info_hash": str(i) * 40,
                 "seeders": 10, "leechers": 1, "size": 1024}
                for i, (name, source) in enumerate((("Alpha", "Nyaa"), ("Beta", "Knaben")))]
        screen = Console(file=io.StringIO(), width=235, height=60)
        with patch.object(table, "console", screen), \
             patch.object(table.readchar, "readkey", side_effect=["f", " ", "\x1b"]), \
             patch.object(table, "refine_results", return_value=("Alpha", "all", "relevance")), \
             patch.object(table, "_source_counts", wraps=table._source_counts) as counts:
            table.interactive_select(rows)
        self.assertEqual(counts.call_count, 2)
        self.assertEqual(len(counts.call_args.args[0]), 1)

    def test_retry_recounts_sources_when_result_count_and_identity_are_unchanged(self):
        from torrent_finder.search_session import SearchResults
        row = {"name": "Alpha", "source": "Nyaa", "info_hash": "a" * 40,
               "seeders": 10, "leechers": 1, "size": 1024}
        session = Mock(diagnostics=[], can_retry=True)
        rows = SearchResults([row], session=session)
        updated = SearchResults([dict(row, source="Knaben")])
        screen = Console(file=io.StringIO(), width=235, height=60)
        with patch.object(table, "console", screen), \
             patch.object(table.readchar, "readkey", side_effect=["r", " ", "\x1b"]), \
             patch("torrent_finder.ui.search_diagnostics.run_action", return_value=(updated, "")), \
             patch.object(table, "_source_counts", wraps=table._source_counts) as counts:
            table.interactive_select(rows)
        self.assertEqual(counts.call_count, 2)
        self.assertEqual(counts.call_args.args[0][0]["source"], "Knaben")
