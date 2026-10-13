"""Appearance translates at draw time and keeps persisted and Terminal identities."""

import copy
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

import isolation  # noqa: F401 -- redirects persistence before app imports
from isolation import isolate_store
from torrent_finder import i18n, paintings, terminal_profile
from torrent_finder.ui import appearance, selector, theme


@contextmanager
def menu_fixture(palette="citrinitas", *, installed=False, look="full", action=None):
    """Capture the real menu, with every OS/profile operation replaced."""
    old_theme = theme.current()
    old_session = copy.deepcopy(appearance._session)
    theme.apply(palette, focus="fill", density="comfortable")
    appearance._session.update(copy.deepcopy(appearance.DEFAULTS), source="saved")
    appearance._session["profile"]["look"] = look
    captured = {}

    def select(items, **kwargs):
        captured.update(kwargs, items=items)
        if action:
            action(items, kwargs)

    try:
        with ExitStack() as stack:
            for name, result in {
                "supported": True, "installed": installed, "in_profile": False,
                "font_installed": False, "missing_fonts": [], "install_fonts": [],
                "folder": Path("fixture/profile"), "write": Path("fixture/profile/torrent-finder.json"),
                "remove": None, "refresh": True,
            }.items():
                captured[name] = stack.enter_context(patch.object(terminal_profile, name, return_value=result))
            stack.enter_context(patch.object(paintings, "export_folder", return_value=Path("fixture/paintings")))
            captured["export"] = stack.enter_context(patch.object(
                paintings, "export", return_value=Path("fixture/paintings/torrent-finder-dore-satan-citrinitas.png")))
            captured["confirm"] = stack.enter_context(patch(
                "torrent_finder.ui.prompts.confirm_prompt", return_value=True))
            stack.enter_context(patch.object(selector, "arrow_select", side_effect=select))
            appearance.appearance_menu()
            yield captured
    finally:
        appearance._session.clear()
        appearance._session.update(old_session)
        theme.apply(old_theme[0].key, focus=old_theme[1], density=old_theme[2])


class AppearanceLanguageTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)
        self.addCleanup(i18n.use, "en")

    def test_painting_display_switches_without_changing_catalogue_records(self):
        entries = paintings.catalog()
        originals = {key: (entry.title, entry.artist, entry.work, entry.credit, entry.file)
                     for key, entry in entries.items()}
        i18n.use("pt-BR")
        self.assertEqual(entries["dore-raven"].title_label(), "O Corvo")
        self.assertEqual(entries["smith-hermit"].title_label(), "O Eremita")
        self.assertEqual(entries["durer-melencolia"].title_label(), "Melencolia I")
        self.assertEqual(entries["flammarion"].artist_credit_label(), "Artista desconhecido, 1888")
        self.assertEqual(entries["dore-satan"].credit_label(), "Gustave Doré, 1866 (Paraíso Perdido)")
        self.assertIn("Matthäus Merian, para Michael Maier", entries["maier-emblem"].credit_label())
        self.assertEqual(originals, {key: (entry.title, entry.artist, entry.work, entry.credit, entry.file)
                                     for key, entry in entries.items()})
        self.assertEqual(set(paintings._TITLES), {entry.title for entry in entries.values()})
        self.assertEqual(set(paintings._WORKS), {entry.work for entry in entries.values() if entry.work})
        i18n.use("en")
        for entry in entries.values():
            self.assertEqual(entry.title_label(), entry.title)
            self.assertEqual(entry.credit_label(), entry.credit)

    def test_display_copies_match_the_english_theme_registry(self):
        self.assertEqual(appearance._DESIGN_NOTES, {key: value.note for key, value in theme.DESIGNS.items()})
        self.assertEqual(appearance._PALETTE_NOTES, {key: value.note for key, value in theme.THEMES.items()})
        self.assertEqual(appearance._FOCUS_LABELS, theme.FOCUS_STYLES)
        self.assertEqual(appearance._DENSITY_LABELS, theme.DENSITIES)

    def test_menu_translates_labels_and_preserves_values_and_state_colours(self):
        with menu_fixture(installed=True) as english:
            values = [row.value for row in english["items"]]
        i18n.use("pt-BR")
        with menu_fixture(installed=True) as portuguese:
            self.assertEqual(values, [row.value for row in portuguese["items"]])
            rows = {row.value: row for row in portuguese["items"]}
            self.assertEqual(portuguese["title"], "Configurações › Aparência")
            for value, label in [(('placement', 'right'), 'Direita'), (('placement', 'left'), 'Esquerda'),
                                 (('placement', 'facing'), 'Ambos os lados'), (('density', 'compact'), 'Compacta'),
                                 (('focus', 'fill'), 'Linha preenchida'), (('painting', 'dore-raven'), 'O Corvo')]:
                self.assertEqual(rows[value].label, label)
            self.assertEqual(rows[("theme", "citrinitas")].label, "Citrinitas")
            self.assertIn("Âmbar de lamparina", rows[("theme", "citrinitas")].description)
            self.assertEqual(rows[("open", True)].hint.plain, "Não")
            self.assertEqual(str(rows[("open", True)].hint.style), theme.state_style("Off"))

    def test_every_owned_description_and_label_passes_through_qps(self):
        for palette, installed, look in [("citrinitas", False, "full"), ("citrinitas", True, "plain"),
                                          ("quiet", True, "full")]:
            i18n.use("qps")
            with menu_fixture(palette, installed=installed, look=look) as menu:
                for row in menu["items"]:
                    if row.description:
                        self.assertIn("~", row.description, row.value)  # prose starting with A looks like a key bar
                    if row.value == "section_header" and row.label == "─── Windows Terminal ───":
                        continue
                    if isinstance(row.value, tuple) and row.value[0] in ("font", "size", "design", "theme"):
                        continue  # proper names and units
                    self.assertIn("⟦", row.label, row.value)

    def test_saved_choices_remain_keys_in_portuguese(self):
        i18n.use("pt-BR")
        def choose(items, kwargs):
            for value in [("painting", "dore-raven"), ("placement", "facing"), ("focus", "bar"),
                          ("density", "compact"), ("look", "plain"), ("open", True)]:
                index = next(i for i, row in enumerate(items) if row.value == value)
                kwargs["on_action"](index, items)
        with menu_fixture(installed=True, action=choose):
            saved = appearance.saved()
            self.assertEqual([saved[key] for key in ("painting", "placement", "focus", "density")],
                             ["dore-raven", "facing", "bar", "compact"])
            self.assertEqual(saved["profile"], {"look": "plain", "open_from_tabs": True})

    def test_space_on_every_non_theme_row_has_no_side_effects(self):
        kinds = set()

        def preview_rows(items, kwargs):
            before = copy.deepcopy(appearance._session)
            colours = theme.current()
            rows = copy.deepcopy(items)
            for index, row in enumerate(items):
                if not isinstance(row.value, tuple) or row.value[0] in ("theme", "design"):
                    continue
                kinds.add(row.value[0])
                with self.subTest(row=row.value):
                    kwargs["key_actions"][" "](index, items)
                    self.assertEqual(appearance._session, before)
                    self.assertEqual(theme.current(), colours)
                    self.assertEqual(items, rows)

        for installed in (False, True):
            with patch.object(appearance, "save") as save:
                with menu_fixture(installed=installed, action=preview_rows) as menu:
                    for operation in ("write", "remove", "export", "confirm", "install_fonts", "refresh"):
                        menu[operation].assert_not_called()
                save.assert_not_called()
        self.assertEqual(kinds, {"painting", "placement", "export", "font", "size", "focus", "density",
                                 "look", "open", "profile"})

    def test_terminal_fragment_is_identical_in_every_language(self):
        data = []
        for language in ("en", "pt-BR", "qps"):
            i18n.use(language)
            data.append(terminal_profile.fragment(theme.THEMES["citrinitas"], Path("dore-raven.png"),
                        terminal_profile.default_font("athanor"), ["torrent-finder"], "%USERPROFILE%"))
        self.assertEqual(data[0], data[1])
        self.assertEqual(data[0], data[2])
        self.assertEqual(data[1]["profiles"][0]["name"], "torrent-finder")
        self.assertEqual(data[1]["profiles"][0]["colorScheme"], "torrent-finder Citrinitas")

    def test_profile_confirmation_and_saved_notice_are_localized(self):
        i18n.use("pt-BR")
        def choose(items, kwargs):
            for value in [("profile", "add"), ("export", None)]:
                kwargs["on_action"](next(i for i, row in enumerate(items) if row.value == value), items)
        with menu_fixture(action=choose) as menu:
            message = menu["confirm"].call_args.args[0]
            self.assertIn("Adicionar um perfil [bold]torrent-finder[/bold] ao Windows Terminal?", message)
            self.assertIn("Satan in profile atrás do texto", message)
            self.assertIn("[good]Salvo[/good] torrent-finder-dore-satan-citrinitas.png", menu["footer"]())
            self.assertEqual(menu["write"].call_args.args[1], "dore-satan")

    def test_private_folder_error_preserves_file_name_and_path(self):
        i18n.use("pt-BR")
        private = Mock()
        private.parent = Path("fixture/private")
        with patch.object(terminal_profile, "_private_copy", return_value=private):
            with self.assertRaisesRegex(OSError, "O Windows manteve torrent-finder.json"):
                terminal_profile._check_real(Path("torrent-finder.json"))


if __name__ == "__main__":
    unittest.main()
