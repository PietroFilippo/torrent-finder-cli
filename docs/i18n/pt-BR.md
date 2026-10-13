# Brazilian Portuguese (pt-BR): style guide

For whoever translates torrent-finder into Brazilian Portuguese, person or
agent. The terms below are also in [pt-BR.glossary.json](pt-BR.glossary.json),
which `python scripts/i18n.py todo pt-BR` shows beside each message and
`python scripts/i18n.py check pt-BR` enforces. How the machinery works:
[ADR-0028](../adr/0028-interface-languages.md); how to run the tools:
[Translating](../development.md#translating).

## Voice

- **Você**, present tense, terse. Say what happens, not what "will" happen:
  "Salvo em {folder}", not "O arquivo foi salvo com sucesso em {folder}".
- No "por favor", no exclamation marks (except *Até logo!*).
- Titles, menu rows and badges in sentence case: "Filmes e séries", not
  "Filmes E Séries". Section labels are drawn in capitals by the app; write
  them in sentence case.
- Portuguese runs about a third longer than English. Where a message has a
  width budget, `todo` shows it; elsewhere still prefer the shorter word.

## Keys

- Key names stay English: **Enter, Esc, Tab, Space, Ctrl, Shift, Alt, PgUp,
  PgDn, Home, End, Backspace, Del**. They are the legends on Brazilian ABNT2
  keyboards, and the key bar reads them by name ("Space" included).
- Hotkey letters never change with the language: `F filtros`, `H histórico`,
  `S estatísticas`, `b favorito`. The letter stays even when the
  Portuguese word does not start with it.
- Key bars use lowercase infinitives: `Enter selecionar  •  Esc voltar`,
  `↑/↓ navegar`, `Tab ações`, `? teclas`. The action must start with a plain
  letter (A-Z), a digit or `(`, or the bar reads it as prose: write
  `Esc voltar`, never an action that begins with an accented letter.
- Prose uses the imperative: "Pressione F para filtrar", "Pressione
  [key]qualquer tecla[/key] para continuar…".
- Yes/no prompts will accept **S** and **sim** as well as Y in pt-BR (a later
  phase wires the keys). Until then keep the prompt's letter: `Y confirmar`.

## Words

| English | pt-BR | Not |
| --- | --- | --- |
| provider | categoria | provedor |
| provider group (Games, Software, Manga) | categoria, with subcategorias or fontes | |
| engine | mecanismo | motor |
| source | fonte | |
| preset | filtro | predefinição, preset |
| search | buscar (verb), busca (noun) | pesquisar, pesquisa |
| bookmark | favorito | marcador |
| download | baixar (verb), download (noun) | descarregar, transferência |
| stream | assistir (stream), transmitir | |
| subtitles | legendas | |
| dubbed | dublado | dobrado |
| settings | Configurações | definições |
| credentials | Credenciais | |
| What's Next? | E agora? | |
| Goodbye! | Até logo! | |
| file / screen / user | arquivo / tela / usuário | ficheiro / ecrã / utilizador |

A **provider** is what the user is looking for, not who serves it: the main
menu lists *Filmes e séries*, *Jogos*, *Anime*. "Provedor" reads like an
internet provider. *Filtros e mecanismos* is the screen of presets and
engines; "predefinição" is too long for a badge.

**Badges** must stay short; the selector sizes the badge column to the
longest state:

| Context | English | pt-BR |
| --- | --- | --- |
| `engine mode` | On / Auto / Off | Sempre / Auto / Nunca |
| `preset state` | Off / Require / Prefer | Não / Exigir / Preferir |

**Scene jargon stays English**: torrent (never "torrente"), magnet (*link
magnet*), seeds, leechers, swarm, release. Units (GB, MB/s) stay as they are.

## Names never translated

- The designs **Athanor** and **Simple**; the colourways **Citrinitas,
  Rubedo, Albedo, Viriditas, Nigredo** (Latin); the Simple themes **Quiet
  Blue, Iris, Lagoon, Ember, Mono, Paper**.
- Font names (PxPlus IBM VGA 8x16, Cascadia Mono…).
- Painting titles and the works they come from stay in English unless
  Portuguese has an established title: *O Corvo*, *Caronte*, *A gravura de
  Flammarion*, *O Eremita*, *Paraíso Perdido*, *Dom Quixote*, *Tarô
  Rider–Waite*. When Portuguese editions disagree (Coleridge's *The Rime of
  the Ancient Mariner*), keep the English.
- Torrent Finder, torrent-finder, Windows Terminal, qBittorrent, source and
  site names (Apibay, Knaben, Nyaa, RuTracker, FitGirl…).
- Command-line flags (`--theme`, `-t`), file names (`filter_state.json`),
  environment variables, URLs: the check fails when one goes missing.

## Athanor's voice

The Athanor design (the default) speaks like a roguelike or a MUD. Keep that
register in Portuguese; alchemical words are welcome (*atanor*, *cadinho*,
*retorta*):

| English | pt-BR |
| --- | --- |
| ~ The Index ~ | ~ O Índice ~ |
| Obvious exits: | Saídas óbvias: |
| --More-- | --Mais-- |
| Searches / Picked / Bookmarks / T (status line) | Buscas / Escolhas / Favoritos / T |
| You feel watched: every peer can see your real IP. | Você se sente observado: todo peer vê seu IP real. |
| A raven arrives: … U installs it. | Um corvo chega: … U o instala. |

## Form

- Keep every `{placeholder}`, Rich tag (`[warn]…[/warn]`, `[key]…[/key]`) in
  the same order, and the separators ` › ` and ` • ` and line breaks in the
  same number.
- Placeholders hold names and numbers whose gender you cannot know: build
  the sentence so nothing agrees with them ("Salvo: {name}", not "{name}
  salvo").
- Counted messages: give `"one"` and `"other"`. Zero takes "other" ("0
  resultados"); add `"zero"` when a sentence reads better ("Nenhum
  resultado").
- Use the same punctuation as the English (the single-character ellipsis
  `…`, straight quotes). Type composed accents (NFC); the check rejects
  decomposed ones.
- Numbers keep the decimal point for now ("1.5 GB"); a decimal comma is a
  later option.
- Contexts in use: `engine mode`, `preset state`, `key bar` (an action word
  on its own, as in `? keys`). Reuse them; a new context needs the same
  string in the code's `ctx=` and the catalogue key (`"ctx::msg"`).
