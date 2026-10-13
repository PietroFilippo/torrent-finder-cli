"""Results, history and tips translate only display labels, including responsive layouts."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import unittest
from unittest.mock import patch

from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

import isolation  # noqa: F401
from torrent_finder import i18n, madokami
from torrent_finder.ui import history, table, theme, tips_page


class ResultsLanguageTests(unittest.TestCase):
    def setUp(self):
        i18n.use("pt-BR")

    def test_history_filter_identities_survive_language_switches(self):
        now = datetime.now(timezone.utc)
        entries = [dict(query=str(days), provider=provider, kind=kind,
                        timestamp=(now - timedelta(days=days)).isoformat())
                   for days, provider, kind in ((0, "movies", "keyword"), (3, "games", "creator"),
                                                 (20, "movies", "keyword"), (50, "manga", "creator"))]
        before = deepcopy(entries)
        for language in ("pt-BR", "qps", "en"):
            i18n.use(language)
            self.assertEqual(history._DATE_OPTIONS, ["All time", "Today", "This week", "This month"])
            self.assertEqual(history._SORT_OPTIONS, ["Newest first", "Oldest first"])
            self.assertEqual(history._TYPE_OPTIONS, ["All", "Keyword", "By-creator"])
            self.assertEqual(history._PROVIDER_OPTIONS[0], None)
            for option, count in zip(history._DATE_OPTIONS, (4, 1, 2, 3)):
                self.assertEqual(len(history._filter_by_date(entries, option)), count)
            self.assertEqual(history._filter_by_provider(entries, "games"), [entries[1]])
            self.assertEqual(history._filter_by_type(entries, "By-creator"), [entries[1], entries[3]])
            self.assertEqual(history._filter_by_type(entries, "Keyword"), [entries[0], entries[2]])
            self.assertEqual(history._sort_entries(entries, "Newest first"), entries)
            self.assertEqual(history._sort_entries(entries, "Oldest first"), entries[::-1])
        self.assertEqual(entries, before)

    def test_history_draws_translated_filters_and_presets_but_returns_saved_entry(self):
        entry = dict(query="Back", provider="movies", presets=["Dual audio"],
                     timestamp=datetime.now(timezone.utc).isoformat())
        before = deepcopy(entry)

        def select(items, **kwargs):
            self.assertEqual(items[0].label, "Back")
            self.assertIn(i18n.t("Dual audio"), items[0].hint)
            self.assertIn("D data: Todo o período", kwargs["footer"]())
            self.assertIn("S ordenar: Mais recentes", kwargs["footer"]())
            kwargs["key_actions"]["D"](0, items)
            kwargs["key_actions"]["S"](0, items)
            kwargs["key_actions"]["T"](0, items)
            self.assertIn("Hoje", kwargs["title"]())
            self.assertIn("Mais antigos", kwargs["title"]())
            self.assertIn("Palavra-chave", kwargs["title"]())
            kwargs["key_actions"]["P"](0, items)
            self.assertEqual(items[0].value, entry)
            self.assertIn(history._option_label("movies"), kwargs["footer"]())
            return 0

        with patch.object(history, "load_history", return_value=[entry]), \
             patch.object(history, "arrow_select", side_effect=select):
            self.assertIs(history.history_select_prompt(), entry)
        self.assertEqual(entry, before)

    def test_history_find_remove_undo_keep_data_and_hotkeys(self):
        entry = dict(query="Back", provider="movies", presets=["Dual audio"])
        before = deepcopy(entry)

        def select(items, **kwargs):
            keys, footer = kwargs["key_actions"], kwargs["footer"]
            with patch("torrent_finder.ui.prompts.get_query_with_shortcut", return_value="Back"):
                keys["/"](0, items)
            self.assertIn("Busca: Back", footer())
            self.assertEqual(items[0].value, entry)
            keys["X"](0, items)
            self.assertIn("Removido: “Back”", footer())
            self.assertIn("U desfazer", footer())
            keys["U"](0, items)
            self.assertIn("Restaurado: “Back”", footer())
            self.assertNotIn("U desfazer", footer())
            self.assertEqual(items[0].value, entry)
            return 0

        with patch.object(history, "load_history", return_value=[entry]), \
             patch.object(history, "remove_history_entry") as remove, \
             patch.object(history, "restore_history_entry") as restore, \
             patch.object(history, "arrow_select", side_effect=select):
            self.assertIs(history.history_select_prompt(), entry)
        remove.assert_called_once_with(before)
        restore.assert_called_once_with(before, 0)
        self.assertEqual(entry, before)

    def test_tip_category_identity_and_bilingual_search_are_preserved(self):
        for language in ("pt-BR", "qps", "en"):
            i18n.use(language)
            self.assertIsNone(tips_page._active_category(0))
            for index, category in enumerate(tips_page.TIP_CATEGORIES, 1):
                self.assertEqual(tips_page._active_category(index), category.name)
                items = tips_page._build_items("", index)
                self.assertEqual(items[0].label, f"--- {i18n.t(category.name)} ---")
                rows = [item for item in items if isinstance(item.value, tuple)]
                self.assertEqual(len(rows), len(category.tips))
                for item in rows:
                    self.assertEqual(item.value[1], category.name)
                    self.assertEqual(item.label, item.value[2].display_text())
                tip = category.tips[0]
                self.assertEqual(tips_page._matching_by_category(tip.text, index)[0][0], category)
                self.assertEqual(tips_page._matching_by_category(tip.display_text(), index)[0][0], category)

    def test_tags_match_original_words_and_draw_translated_labels(self):
        name = "[FLUX] Dune 2024 1080p WEB-DL Dual Audio Dublado PT-BR"
        with patch.object(table, "tag_matches", wraps=table.tag_matches) as matches:
            line = table._tags_line(name, ["Dublado (PT-BR)"], 200)
        self.assertIn("áudio PT-BR " + theme.CHECK, line.plain)
        self.assertIn("grupo FLUX", line.plain)
        self.assertIn("PT-BR audio", [call.args[0] for call in matches.call_args_list])

    def test_madokami_and_provider_labels_are_only_translated_for_display(self):
        path = "/Manga/O/ON/ONE_/One%20Piece"
        row = dict(name=madokami.display_name(path), mdk_path=path,
                   provider_label="Manga · Madokami", provider_slug="madokami", source="Madokami")
        before = deepcopy(row)
        for width in (40, 80, 200):
            screen = Console(file=io.StringIO(), width=width, height=50, color_system=None)
            with patch.object(table, "console", screen):
                view = table.build_table([row], 0, 0, 1, 1)
                screen.print(view)
                self.assertEqual(table._result_name(row), "One Piece [pasta da série]")
                self.assertEqual(table._provider_label(row), i18n.t(row["provider_label"]))
                self.assertIn(i18n.t(row["provider_label"]), view.caption.plain)
        self.assertEqual(row, before)

    def test_headers_and_age_cells_fit_after_runtime_language_switch(self):
        row = dict(name="Fixture", source="Nyaa", uploaded_at=1700000000,
                   seeders=123, leechers=45, size=1000)
        for language in ("en", "pt-BR", "qps"):
            i18n.use(language)
            for width in (40, 80, 137, 200):
                screen = Console(file=io.StringIO(), width=width, height=50, color_system=None)
                with patch.object(table, "console", screen):
                    view = table.build_table([row], 0, 0, 1, 1)
                    screen.print(view)
                for column in view.columns:
                    if column.width is not None:
                        self.assertGreaterEqual(column.width, cell_len(column.header))
                self.assertTrue(all(cell_len(line) <= width for line in screen.file.getvalue().splitlines()))
        i18n.use("pt-BR")
        for days, expected in ((0, "1h"), (13, "13d"), (59, "8sem"), (729, "24m"), (1095, "3a")):
            age = table._age(1, now=1 + days * 86400)
            self.assertEqual(age, expected)
            self.assertLessEqual(cell_len(age), table._column_widths()["Age"])

    def test_header_budget_uses_the_drawn_status_template(self):
        theme.apply("quiet")
        screen = Console(file=io.StringIO(), width=80, height=40, color_system=None)
        with patch.object(table, "console", screen), \
             patch.object(theme, "header_lines", wraps=theme.header_lines) as header:
            table._visible_count(10, 40, 80, "", False)
        expected = table.results_status(887, 1, 888, 87, 88, frozenset(range(888)))
        self.assertEqual(header.call_args.args[1], expected)
        self.assertEqual(expected, "888–888 de 888 · página 88/88 · 888 selecionados")

    def test_key_bar_switches_using_translated_width_and_preserves_keys(self):
        for language in ("en", "pt-BR", "qps"):
            i18n.use(language)
            for width, compact in ((80, True), (400, False)):
                with patch.object(table, "console", Console(width=width)):
                    keys = table._result_keys(2, frozenset())
                self.assertIn(i18n.t("↑/↓ move • Space pick • {enter} • i details • b save • f refine",
                                     enter=i18n.t("Enter open")) if compact else
                              i18n.t("↑/↓ navigate • Space select • {enter} • i details • f refine/sort • b bookmark",
                                     enter=i18n.t("Enter open")), keys)
                self.assertEqual(len(theme.parse_footer(Text(keys)).keys), 10)

    def test_view_translates_sort_match_and_summary_without_changing_state(self):
        screen = Console(file=io.StringIO(), width=200, height=50, color_system=None)
        workspace = table.ResultsViewState(query="Back", mode="contains", order="seeds")
        frames = []

        class Live:
            def __init__(self, renderable, **kwargs): frames.append(renderable)
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def update(self, renderable): frames.append(renderable)

        def draw(summary):
            frames.clear()
            with patch.object(table, "console", screen), patch.object(table, "Live", Live), \
                 patch.object(table.readchar, "readkey", return_value=table.readchar.key.ENTER):
                result = table.interactive_select([{"name": "Back"}], view_state=workspace,
                                                 search_summary=summary, search_summary_label="FILTRO TRADUZIDO")
            with screen.capture() as capture:
                screen.print(frames[0])
            self.assertEqual(result, ("one", 0))
            return capture.get()

        output = draw("Prefer: Dual audio")
        self.assertIn("Ordem: Mais seeds", output)
        self.assertIn("Contém: Back", output)
        self.assertIn("FILTRO TRADUZIDO", output)
        self.assertNotIn("FILTRO TRADUZIDO", draw("No presets"))
        self.assertEqual((workspace.query, workspace.mode, workspace.order), ("Back", "contains", "seeds"))


if __name__ == "__main__":
    unittest.main()
