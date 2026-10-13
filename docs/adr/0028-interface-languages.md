# ADR-0028: Interface languages: English as the key, looked up when drawn

Status: accepted (2026-10-13). Phase 1 of three: the infrastructure. No
screen is translated yet and nothing on screen changes.

## Context

Users asked for Brazilian Portuguese, with more languages later. Every
screen writes its English inline: f-strings, footers that `ui/theme.py`
parses into key bars (`"↑/↓ navigate  •  Enter apply  •  Esc back"`), and
module-level help constants (`ui/appearance.PROFILE_HELP`).

Some of that English is also identity. `security.py` builds the network
warning as `(label, value)` rows and masks a value when `label in
masked_labels`, with `masked_labels = ("Public IP", "Location")`.
Translating the label where the row is built ("IP público") makes the test
false, and the frame draws the user's IP unmasked. State words (`On`, `Auto`,
`Off`) are compared the same way, and history, profiles and settings persist
English values. ADR-0001 already separates a provider's `slug` (identity)
from its `name` (display); the same split is needed for every string, and
the safe moment to translate is the last one, when text is drawn.

The display language is not the regional format. The user's own Windows is
in English (display language en-US) with Brazilian dates and numbers
(regional format pt-BR), a common setup in Brazil: the region says where
someone lives, not which language they chose for their computer.

Conversion will be done screen by screen by several agents in parallel, the
suite must keep passing in English on Linux CI under unittest, and the app
ships through PyPI, pipx and PyInstaller binaries, mostly on Windows.

## Decision

**English is the key.** `torrent_finder/i18n.py` (standard library only,
importing nothing from the app, so any module may import it):

- `t(msg, /, *, ctx="", **values)` returns *msg* in the interface language,
  formatted with `str.format(**values)` when values are given (unformatted
  otherwise, so literal braces need no escaping). `ctx` tells identical
  English apart (the catalogue key is `"ctx::msg"`): engine mode `Off` is
  *Nunca*, preset state `Off` is *Não*.
- `tn(singular, plural, n, /, *, ctx="", **values)`, with `{n}` available.
  English and pt-BR use "one" for 1 and "other" otherwise. CLDR and gettext
  put 0 in the singular for Portuguese; the app deliberately says "0
  resultados", which reads better for counts, and an entry may add a "zero"
  form ("Nenhum resultado").
- `N_(msg, /, *, ctx="")` marks text defined at import time for extraction
  and returns it unchanged; with a context it returns a `str` subclass that
  carries it, so `t(MARKED)` finds the right entry. It compares, hashes and
  serialises as the plain string.
- A missing translation shows the English; a translation whose placeholders
  break falls back to the formatted English; nothing raises.
- `use(code)`, `current()`, `languages()` (`{"en": "English", "pt-BR":
  "Português (Brasil)"}`, endonyms never translated) and `normalise(code)`
  (`pt`, `pt_BR`, `ptbr`, `pt-PT.UTF-8` give `pt-BR`; `en_US` gives `en`).

**Catalogues** are JSON objects in `torrent_finder/assets/locales/<code>/`.
Every `*.json` in a language's folder is merged, so each translator (or
agent) owns a file: `common.json` for shared words, one file per converted
module (`ui.appearance.json`). A value is a string, or `{"one", "other",
"zero"}` for a counted message keyed by its singular. They are read on first
use and kept. The package already ships `assets/**`; binaries use
`--collect-data torrent_finder`.

**Translate when drawing.** `t()` is never called at module level, in a
class body, in a default argument value or in a decorator: text is looked up
when a screen draws, so switching language at run time works (the theme's
rule: read `theme.X` at render time). Identity stays English or a key:
comparisons, persisted values and lookups never see a translation.

**Resolution at startup**, before any screen draws: `--lang CODE` (this run;
`auto`, `en`, `pt-BR`, any spelling `normalise` takes, and `qps`, accepted
but not listed), then `TORRENT_FINDER_LANG` (an unknown value is named on
the main menu and ignored, as with the theme), then the saved
`settings.language` (`"auto"`, `"en"` or `"pt-BR"`; missing means auto;
unknown values are ignored silently), then the **display language**, then
English. `auto` at any step asks the system. On Windows the display language
is the first of `GetUserPreferredUILanguages(MUI_LANGUAGE_NAME)`, falling
back to `GetUserDefaultUILanguage`; elsewhere gettext's order: `LANGUAGE`
(its first shipped language) unless the locale is C, then `LC_ALL`,
`LC_MESSAGES`, `LANG`; `C` and `POSIX` are English. Any `pt-*` gives pt-BR.
An in-app restart keeps `--lang` as it keeps `--theme`; the update preview
reads no settings.

The regional format only suggests: `region_suggests(code)` names the
language a Portuguese region suggests while the display language gave
English, and `suggestion()` does so only when nothing chose this run's
language (no flag, no variable, nothing saved). A later phase shows it once:
"Prefere português? Configurações › Idioma". On the user's machine, auto
gives English plus that hint.

**The qps pseudo-locale**, generated from the English with no file, wraps
each message in `⟦ ⟧`, accents its vowels and pads each line or key-bar
segment by about a third with `~`. It leaves alone placeholders, Rich markup
tags, URLs, file names, flags, environment variables, key names and the
separators ` › ` and ` • `. A word's first letter is never accented and a
message that starts with a key gets no brackets, so key bars still read as
keys. A capture in qps shows unconverted text (plain English) and overflow.

**Tooling and checks.** `scripts/i18n.py` reads the package with `ast`:
`extract`, `todo LANG` (each missing message with the code around it, its
width budget, glossary terms and a JSON skeleton: what a translator, person
or agent, reads), `check [LANG]`, `stats` and `bare FILE...`. Marks live in
comments beside the code, so parallel conversions edit no shared list:
`# i18n: converted` on a module's own line puts it under the bare-literal
ratchet, `# i18n: ignore` exempts a line, `# i18n: budget=N` caps a
translation's width in cells. `tests/test_i18n.py` runs the same checks and
fails on:

- `t()`/`tn()` at import time; an f-string or computed message (a variable
  is fine: N_-marked text); a computed `ctx`; placeholders without values,
  positional `{}` fields, doubled braces shown unformatted;
- bare UI literals in converted modules;
- a message missing from a shipped catalogue, or an obsolete entry (the seed
  entries are `RESERVED` until code uses them); one key translated
  differently in two files; a locale folder that is not a shipped language;
- per translation: different placeholders, a different sequence of Rich
  tags or text Rich cannot read, a different count of ` › `, ` • ` or line
  breaks, a lost flag, file name, URL, variable, `Ctrl+` key or the key after
  "Press", a key bar that no longer reads as the same keys in the same order
  (an action must start with a plain letter, a digit or `(`), non-NFC text,
  a width over its budget, the wrong plural shape, and the glossary:
  forbidden words, exact badge words, names never translated.

**Glossary and style.** `docs/i18n/pt-BR.md` is the style guide;
`docs/i18n/pt-BR.glossary.json` is its machine-readable part, outside the
package so the app never loads it. Provider is *categoria*, engine
*mecanismo*, source *fonte*, preset *filtro*, search *buscar*/*busca*,
bookmark *favorito*, settings *Configurações*; engine modes *Sempre / Auto /
Nunca*, preset states *Não / Exigir / Preferir*. Key names and hotkey
letters stay as they are; theme, colourway, font and painting names, and
Athanor, are never translated.

## Rejected

- **gettext `.po`/`.mo`**: GNU `msgfmt` does not come with Windows, so every
  catalogue change would need a build tool installed first, and compiled
  `.mo` files are binary: they cannot be reviewed and conflict whenever two
  branches translate at once. JSON needs no build
  step, diffs line by line and splits into one file per translator. A `.po`
  export stays possible if a translation platform ever wants one.
- **Keyed IDs** (`t("settings.appearance.title")`): the code loses its
  readable English, every string needs an invented name, a missing entry
  shows an ID instead of English, and persisted English values and identity
  comparisons would need a mapping.
- **Translated constants at import**: the language would be fixed by import
  order, a run could not switch, and tests would capture whichever language
  was active when a module loaded.
- **Following the regional format**: it would put most English-Windows users
  in Brazil into Portuguese against the language they chose for their system.
- **Babel or CLDR data**: a dependency for two languages whose plural rule is
  one line.

## Consequences

- Phases. **1** (this ADR): the module, `--lang`, the saved setting read at
  startup, the seed catalogue, the tools, the glossary and the style guide.
  **2**: screens converted module by module, each adding its catalogue file
  and its `# i18n: converted` line, translated in the same change (the
  missing-message check is the gate); a qps mode for
  `scripts/ui_snapshots.py` and a `leaks` command that finds English left in
  qps captures. **3**, after the user approves its design: a Settings ›
  Language row that saves `settings.language`, the one-time regional hint,
  yes/no prompts that accept S and *sim* in pt-BR, `language` in
  `settings_backup.PREFERENCES` if it should travel with backups, and the
  README and guide.
- A screen builds its text when it draws. Before a string is converted, any
  comparison or persistence that uses it moves to a key; `security.py`'s
  masked labels are the known case.
- The suite runs in English: `tests/isolation.py` uses English, removes
  `TORRENT_FINDER_LANG` and makes the system probes answer en-US around every
  test. A test of a translated screen applies its language itself.
- Key bars stay parseable: a translated action starts with an ASCII letter,
  a digit or `(` (ui/theme.py's footer parser), which the check enforces.
- `--help` and argument errors speak the language too: `main._early_language`
  resolves it (from `--lang`, the environment and the saved choice) before the
  parser is built, and `main._speak_argparse` looks argparse's own words up
  under the context `argparse` (listed in `scripts/i18n.py`'s `ARGPARSE`, since
  no `t()` call in this tree names them).
- Numbers keep the decimal point; a decimal comma for pt-BR is a later
  option.
