"""Translation tools: the messages in the code, what a language still lacks, and the checks.

    python scripts/i18n.py extract [--json]                        # every t()/tn()/N_() message, with file:line
    python scripts/i18n.py todo pt-BR [--files a.py ...] [--json]  # what pt-BR lacks, with code and glossary
    python scripts/i18n.py check [pt-BR]                           # catalogue and code checks; exit 1 on a problem
    python scripts/i18n.py stats                                   # messages and translations per module
    python scripts/i18n.py bare FILE...                            # literals that look like UI text, not converted

Marks in the code, read from comments:

- ``# i18n: converted`` on a line of its own: the module's UI text is all
  converted, so a bare UI literal in it fails the check.
- ``# i18n: ignore`` on a line: its literals are not UI text (or stay English).
- ``# i18n: budget=N`` on a line of a ``t()`` call: its translation may take
  at most N cells (a column header, a badge).

``tests/test_i18n.py`` runs the same checks under both test runners. See
docs/adr/0028-interface-languages.md and the Translating section of
docs/development.md.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import string
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from torrent_finder import i18n  # noqa: E402

PACKAGE = ROOT / "torrent_finder"
GLOSSARIES = ROOT / "docs" / "i18n"
FUNCTIONS = ("t", "tn", "N_")

CONVERTED_MARK = re.compile(r"^[ \t]*#\s*i18n:\s*converted\b", re.MULTILINE)
IGNORE_MARK = re.compile(r"#\s*i18n:\s*ignore\b")
BUDGET_MARK = re.compile(r"#\s*i18n:\s*budget\s*=\s*(\d+)")

# Shared messages the seed catalogue (common.json) holds before code uses them:
# the screens that do are converted in later phases. Listed so the catalogue
# check does not call them obsolete; harmless once code uses them too.
RESERVED = [
    ("Back", ""),
    ("Settings", ""),
    ("Press [key]any key[/key] to continue…", ""),
    ("↑/↓ navigate", ""),
    ("Enter select", ""),
    ("Enter choose", ""),
    ("Enter confirm", ""),
    ("Enter search", ""),
    ("Enter save", ""),
    ("Esc back", ""),
    ("Esc cancel", ""),
    ("keys", "key bar"),
    ("On", "engine mode"),
    ("Auto", "engine mode"),
    ("Off", "engine mode"),
    ("Off", "preset state"),
    ("Require", "preset state"),
    ("Prefer", "preset state"),
]

# Calls and keywords whose string arguments are never UI text (for the bare-literal check).
NON_UI_CALLS = {
    "getattr", "setattr", "hasattr", "delattr", "isinstance", "issubclass", "open", "Path", "compile", "match",
    "fullmatch", "search", "sub", "subn", "findall", "finditer", "split", "rsplit", "get", "pop", "setdefault",
    "startswith", "endswith", "strip", "lstrip", "rstrip", "replace", "partition", "rpartition", "index", "find",
    "rfind", "count", "encode", "decode", "removeprefix", "removesuffix", "join", "strftime", "strptime", "getenv",
    "load_setting", "save_setting", "commit_setting", "section", "add_argument", "add_parser", "import_module",
    "namedtuple", "TypeVar", "debug", "Popen", "run", "check_output", "check_call", "call", "which", "glob",
    "rglob", "mkdtemp", "NamedTemporaryFile", "TemporaryDirectory", "with_suffix", "with_name", "joinpath",
    "unpack", "pack", "cast", "patch", "object", "field", "WinDLL", "Style", "parse", "parse_args",
}
NON_UI_KEYWORDS = {
    "ctx", "justify", "overflow", "align", "vertical", "end", "sep", "encoding", "errors", "mode", "newline",
    "spinner", "key", "slug", "kind", "format", "color_system", "box", "method", "dest", "metavar", "action",
}
_KEY_NAMES = (r"(?:Enter|Esc|Tab|Space|Backspace|Delete|Del|PgUp|PgDn|Home|End|F\d{1,2}"
              r"|(?:Ctrl|Shift|Alt)\+(?:[A-Za-z0-9]+|[↑↓←→,.])|[A-Z0-9])")
_PRESS_KEY = re.compile(rf"\b[Pp]ress (?:\[key\])?({_KEY_NAMES})(?![\w+])")
_RICH_TAG = re.compile(r"(\\*)\[([a-z#/@][^\[]*?)]")  # rich.markup's own pattern
_SEPARATORS = {"›": re.compile(r"\s›\s"), "•": re.compile(r"\s•\s"), "line break": re.compile(r"\n")}
_TOKEN_KINDS = ("url", "file", "flag", "env", "combo")


# --- what the code says ----------------------------------------------------------------

@dataclass
class Site:
    """Where a message is used: a t(), tn() or N_() call."""
    file: str        # relative to the repository, with forward slashes
    line: int
    end: int
    function: str    # the enclosing function or class, or <module>
    kind: str        # t, tn or N_
    budget: int | None = None

    def __str__(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass
class Message:
    msgid: str
    ctx: str = ""
    plural: str | None = None  # tn()'s plural form
    sites: list[Site] = field(default_factory=list)
    reserved: bool = False

    @property
    def key(self) -> str:
        return f"{self.ctx}::{self.msgid}" if self.ctx else self.msgid

    @property
    def budget(self) -> int | None:
        budgets = [site.budget for site in self.sites if site.budget is not None]
        return min(budgets) if budgets else None


@dataclass(frozen=True)
class Problem:
    where: str
    check: str
    detail: str

    def __str__(self) -> str:
        return f"{self.where}: [{self.check}] {self.detail}"


@dataclass
class Dynamic:
    """A t() or tn() whose message is a variable: fine for N_()-marked text, listed for review."""
    site: Site
    expression: str


@dataclass
class Extraction:
    messages: dict[str, Message] = field(default_factory=dict)
    dynamic: list[Dynamic] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    converted: list[str] = field(default_factory=list)

    def add(self, message: Message, site: Site) -> None:
        known = self.messages.get(message.key)
        if known is None:
            known = self.messages[message.key] = message
        elif (known.plural is None) != (message.plural is None) and known.sites:
            self.problems.append(Problem(str(site), "plural",
                                         f"{message.key!r} is used both as a counted and as a plain message"))
        elif message.plural is not None and known.plural not in (None, message.plural):
            self.problems.append(Problem(str(site), "plural",
                                         f"{message.key!r} has two plural forms: {known.plural!r}, {message.plural!r}"))
        known.plural = known.plural or message.plural
        known.sites.append(site)


def fields(text: str) -> set[str] | None:
    """The names of *text*'s ``{placeholders}``; None when its braces are malformed."""
    try:
        return {name.split(".")[0].split("[")[0] for _, name, _, _ in string.Formatter().parse(text)
                if name is not None}
    except ValueError:
        return None


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _aliases(tree: ast.AST, relative: str) -> tuple[dict[str, str], set[str]]:
    """Local names of t/tn/N_, and names bound to the i18n module itself."""
    if relative == "torrent_finder/i18n.py":
        return {name: name for name in FUNCTIONS}, set()
    names, modules = {}, {"torrent_finder.i18n"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "torrent_finder.i18n" or (node.level and module == "i18n"):
                names.update((alias.asname or alias.name, alias.name) for alias in node.names
                             if alias.name in FUNCTIONS)
            elif module == "torrent_finder" or (node.level and not module):
                modules.update(alias.asname or alias.name for alias in node.names if alias.name == "i18n")
        elif isinstance(node, ast.Import):
            modules.update(alias.asname for alias in node.names
                           if alias.name == "torrent_finder.i18n" and alias.asname)
    return names, modules


def _literal(node) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


class _Calls(ast.NodeVisitor):
    """Collects t()/tn()/N_() calls with where they run."""

    def __init__(self, relative: str, lines: list[str], names: dict, modules: set, out: Extraction):
        self.relative, self.lines, self.names, self.modules, self.out = relative, lines, names, modules, out
        self.scope: list[str] = []
        self.depth = 0          # function bodies (and lambdas) we are inside: deferred code
        self.defaults = 0       # default argument values and decorators: run when the def runs

    def kind(self, func) -> str | None:
        if isinstance(func, ast.Name):
            return self.names.get(func.id)
        if isinstance(func, ast.Attribute) and func.attr in FUNCTIONS:
            try:
                return func.attr if ast.unparse(func.value) in self.modules else None
            except Exception:
                return None
        return None

    def site(self, node, kind: str) -> Site:
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        budget = None
        for number in range(node.lineno, end + 1):
            match = BUDGET_MARK.search(self.lines[number - 1]) if number <= len(self.lines) else None
            if match:
                budget = int(match.group(1))
        return Site(self.relative, node.lineno, end, ".".join(self.scope) or "<module>", kind, budget)

    def _definition(self, node, body_name: str | None) -> None:
        self.defaults += 1
        for decorator in getattr(node, "decorator_list", []):
            self.visit(decorator)
        arguments = node.args
        for value in arguments.defaults + [value for value in arguments.kw_defaults if value is not None]:
            self.visit(value)
        self.defaults -= 1
        if body_name is not None:
            self.scope.append(body_name)
        self.depth += 1
        for statement in (node.body if isinstance(node.body, list) else [node.body]):
            self.visit(statement)
        self.depth -= 1
        if body_name is not None:
            self.scope.pop()

    def visit_FunctionDef(self, node):
        self._definition(node, node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        self._definition(node, None)

    def visit_ClassDef(self, node):
        for child in node.decorator_list + node.bases + [keyword.value for keyword in node.keywords]:
            self.visit(child)
        self.scope.append(node.name)
        for statement in node.body:
            self.visit(statement)  # a class body runs when the class is defined
        self.scope.pop()

    def problem(self, site: Site, check: str, detail: str) -> None:
        self.out.problems.append(Problem(str(site), check, detail))

    def visit_Call(self, node):
        kind = self.kind(node.func)
        if kind:
            self.call(node, kind)
        self.generic_visit(node)

    def call(self, node, kind: str) -> None:
        site = self.site(node, kind)
        if kind != "N_" and (self.depth == 0 or self.defaults):
            where = "a default argument value or decorator" if self.defaults else "import time"
            self.problem(site, "import-time", f"{kind}() runs at {where}: mark the text with N_() and call "
                                              f"{kind}() when drawing")
        keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
        splat = any(keyword.arg is None for keyword in node.keywords)
        ctx = ""
        if "ctx" in keywords:
            ctx = _literal(keywords["ctx"])
            if ctx is None:
                self.problem(site, "computed", f"{kind}()'s ctx must be a string literal")
                return
        values = set(keywords) - {"ctx"}
        needed = 2 if kind == "tn" else 1
        if len(node.args) < needed:
            self.problem(site, "computed", f"{kind}() needs its message as a positional argument")
            return
        texts = [_literal(argument) for argument in node.args[:needed]]
        if kind == "tn":
            if None in texts:
                self.problem(site, "computed", "tn()'s singular and plural must be string literals")
                return
            self.message(site, texts[0], ctx, values | {"n"}, splat, plural=texts[1])
            return
        argument = node.args[0]
        if texts[0] is not None:
            self.message(site, texts[0], ctx, values, splat)
        elif kind == "t" and isinstance(argument, ast.IfExp) and _literal(argument.body) is not None \
                and _literal(argument.orelse) is not None:
            for branch in (argument.body, argument.orelse):  # t("On" if on else "Off")
                self.message(site, _literal(branch), ctx, values, splat)
        elif kind == "t" and isinstance(argument, (ast.Name, ast.Attribute, ast.Subscript, ast.IfExp)):
            self.out.dynamic.append(Dynamic(site, ast.unparse(argument)))
        else:
            what = "an f-string" if isinstance(argument, ast.JoinedStr) else "computed text"
            self.problem(site, "computed", f"{kind}() gets {what}: no catalogue can hold it; use a literal "
                                           f"with {{placeholders}} and values")

    def message(self, site: Site, text: str, ctx: str, values: set, splat: bool, plural: str | None = None) -> None:
        names = set()
        for template in filter(None, (text, plural)):
            found = fields(template)
            if found is None:
                self.problem(site, "placeholders", f"malformed braces in {template!r}")
                return
            names |= found
        if "" in names or any(name.isdigit() for name in names):
            self.problem(site, "placeholders", f"{text!r} has positional {{}} fields: name them")
        missing = sorted(name for name in names - values if name and not name.isdigit())
        if missing and not splat and site.kind != "N_":  # N_() text gets its values at its t() call
            self.problem(site, "placeholders", f"{text!r} has no value for {', '.join(missing)}")
        if site.kind == "t" and not values and not splat and ("{{" in text or "}}" in text):
            self.problem(site, "placeholders", f"{text!r} is shown unformatted without values: write single braces")
        if not unicodedata.is_normalized("NFC", text + (plural or "")):
            self.problem(site, "nfc", f"{text!r} is not in NFC")
        if site.budget is not None and _cells(text) > site.budget:
            self.problem(site, "budget", f"the English {text!r} is wider than its budget of {site.budget}")
        self.out.add(Message(text, ctx, plural), site)


def modules(root: Path = PACKAGE) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def extract(paths: list[Path] | None = None, reserved: bool = True) -> Extraction:
    """Every message in *paths* (the package by default), with the code problems found on the way."""
    out = Extraction()
    for path in paths if paths is not None else modules():
        relative = _relative(path)
        source = path.read_text(encoding="utf-8")
        if "i18n" in source:  # a module that never names i18n cannot call it
            tree = ast.parse(source, filename=relative)
            names, bound = _aliases(tree, relative)
            _Calls(relative, source.splitlines(), names, bound, out).visit(tree)
        if CONVERTED_MARK.search(source):
            out.converted.append(relative)
    if reserved:
        for msgid, ctx in RESERVED:
            message = Message(msgid, ctx, reserved=True)
            out.messages.setdefault(message.key, message).reserved = True
    return out


# --- bare UI literals ----------------------------------------------------------------

_UI_TOKENS = re.compile("|".join(f"(?:{pattern.pattern})" for pattern in i18n.PROTECTED.values()))


def looks_like_ui(text: str, keep: tuple[str, ...] = ()) -> bool:
    """Whether a string literal reads as interface text: words in a sentence or a capitalised word."""
    plain = _UI_TOKENS.sub(" ", text)
    for name in keep:
        plain = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", " ", plain)
    if not re.search(r"[^\W\d_]{2,}", plain):
        return False
    token = text.strip()
    if any(character.isspace() for character in token):
        return True
    return bool(re.fullmatch(r"[^\W\d_]{2,}[!?.…:]?", token)) and token[0].isupper() and not token.isupper()


def _call_name(func) -> str:
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else ""


def bare_literals(path: Path, keep: tuple[str, ...] | None = None) -> list[tuple[int, str]]:
    """String literals in *path* that look like UI text and reach no t()/tn()/N_(): (line, text)."""
    keep = all_kept() if keep is None else keep
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    names, bound = _aliases(tree, _relative(path))
    marker = _Calls(_relative(path), lines, names, bound, Extraction())
    skipped: set[int] = set()

    def skip(node) -> None:
        if node is not None:
            skipped.update(id(child) for child in ast.walk(node))

    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and body \
                and isinstance(body[0], ast.Expr) and _literal(body[0].value) is not None:
            skip(body[0])  # a docstring
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            if marker.kind(node.func):
                for argument in node.args[:2]:
                    skip(argument)
                skip(next((keyword.value for keyword in node.keywords if keyword.arg == "ctx"), None))
            elif name in NON_UI_CALLS:
                for argument in node.args + [keyword.value for keyword in node.keywords]:
                    skip(argument)
            for keyword in node.keywords:
                if keyword.arg in NON_UI_KEYWORDS or (keyword.arg or "").endswith("style"):
                    skip(keyword.value)
        elif isinstance(node, ast.Dict):
            for key in node.keys:
                skip(key)
        elif isinstance(node, ast.Subscript):
            skip(node.slice)
        elif isinstance(node, ast.Compare):
            skip(node)
        elif isinstance(node, ast.arg):
            skip(node.annotation)
        elif isinstance(node, ast.AnnAssign):
            skip(node.annotation)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            skip(node.returns)
        elif isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id.startswith("__")
                                                    for target in node.targets):
            skip(node.value)  # __all__, __slots__

    found = []
    for node in ast.walk(tree):
        if id(node) in skipped:
            continue
        if isinstance(node, ast.JoinedStr):
            skipped.update(id(child) for child in ast.walk(node))
            text = "".join(_literal(part) if _literal(part) is not None else "{}" for part in node.values)
        elif _literal(node) is not None:
            text = node.value
        else:
            continue
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        if any(IGNORE_MARK.search(lines[number - 1]) for number in range(node.lineno, end + 1)):
            continue
        if looks_like_ui(text, keep):
            found.append((node.lineno, text))
    return sorted(found)


# --- catalogues ------------------------------------------------------------------------

def shipped() -> list[str]:
    """Languages with catalogues: every shipped language but English, the source."""
    return [code for code in i18n.languages() if code != i18n.DEFAULT]


def load_files(code: str) -> tuple[dict[str, dict], list[Problem]]:
    """Each catalogue file of *code* (name → entries), and problems reading them."""
    files, problems = {}, []
    for path in sorted((i18n.LOCALES / code).glob("*.json")):
        where = _relative(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            problems.append(Problem(where, "file", f"unreadable: {error}"))
            continue
        if not isinstance(data, dict):
            problems.append(Problem(where, "file", "must hold one JSON object"))
            continue
        files[where] = data
    return files, problems


def merged(code: str) -> dict:
    """The entries of *code* as the app merges them (later files win)."""
    entries = {}
    for data in load_files(code)[0].values():
        entries.update(data)
    return entries


def load_glossary(code: str) -> dict:
    path = GLOSSARIES / f"{code}.glossary.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"terms": [], "keep": []}
    return {"terms": data.get("terms", []), "keep": data.get("keep", [])}


def all_kept() -> tuple[str, ...]:
    """Names no language translates, from every glossary."""
    names = set()
    for path in GLOSSARIES.glob("*.glossary.json"):
        names.update(load_glossary(path.name.split(".")[0])["keep"])
    return tuple(sorted(names, key=len, reverse=True))


def _forbidden(pattern: str) -> re.Pattern:
    stem = pattern.rstrip("*")
    tail = r"\w*" if pattern.endswith("*") else ""
    return re.compile(rf"(?<!\w){re.escape(stem)}{tail}(?!\w)", re.IGNORECASE)


def _term(term: str) -> re.Pattern:
    """An English glossary term in a message: any case, a plural s."""
    edge = r"(?!\w)" if term[-1].isalnum() else ""
    return re.compile(rf"(?<!\w){re.escape(term)}(?:s|es)?{edge}", re.IGNORECASE)


def glossary_hits(message: Message, glossary: dict) -> list[dict]:
    hits = []
    for term in glossary["terms"]:
        if term.get("ctx"):
            if term["ctx"] == message.ctx and term["term"] == message.msgid:
                hits.append(term)
        elif any(_term(term["term"]).search(text) for text in filter(None, (message.msgid, message.plural))):
            hits.append(term)
    return hits


def _plain(text: str) -> str:
    from rich.text import Text
    try:
        return Text.from_markup(text).plain
    except Exception:
        return text


def _cells(text: str) -> int:
    from rich.cells import cell_len
    return cell_len(_plain(text))


def _tags(text: str) -> list[str]:
    return [tag for slashes, tag in _RICH_TAG.findall(text) if len(slashes) % 2 == 0]


def _key_bar(text: str) -> list[str] | None:
    """The keys of a key-bar message, as the app's footer parser reads them; None for prose."""
    from torrent_finder.ui import theme
    try:
        footer = theme.parse_footer(text)
    except Exception:
        return None
    if footer.context or not footer.keys:
        return None
    keys = [segment.plain.split(" ", 1) for segment in footer.keys]
    lone = len(keys) == 1 and len(keys[0][0]) == 1 and len(keys[0][1].split()) > 3
    return None if lone else [key for key, _action in keys]  # "A raven arrives: …" is prose


def pair_problems(english: str, text: str, where: str, message: Message, form: str = "") -> list[Problem]:
    """What is wrong with *text* as the translation of *english* (one form of *message*)."""
    problems = []

    def report(check: str, detail: str) -> None:
        problems.append(Problem(where, check, f"{form + ': ' if form else ''}{detail}"))

    if not text.strip():
        report("empty", "the translation is empty")
        return problems
    if not unicodedata.is_normalized("NFC", text):
        report("nfc", "not in NFC: normalise it (unicodedata.normalize('NFC', ...))")
    wanted, found = fields(english), fields(text)
    if found is None:
        report("placeholders", "malformed braces")
    elif wanted is not None:
        optional = {"n"} if form in ("one", "zero") else set()  # "um resultado", "Nenhum resultado"
        if (wanted - optional) != (found - optional) or not found <= wanted | optional:
            report("placeholders", f"{{{', '.join(sorted(found))}}} instead of {{{', '.join(sorted(wanted))}}}")
    if _tags(english) != _tags(text):
        report("markup", f"tags {_tags(text)} instead of {_tags(english)}")
    from rich.text import Text
    try:
        Text.from_markup(text)
    except Exception as error:
        report("markup", f"Rich cannot read it: {error}")
    for name, pattern in _SEPARATORS.items():
        if len(pattern.findall(english)) != len(pattern.findall(text)):
            report("separators", f"{len(pattern.findall(text))} × {name} instead of {len(pattern.findall(english))}")
    for kind in _TOKEN_KINDS:
        for token in i18n.PROTECTED[kind].findall(english):
            if text.count(token) < english.count(token):
                report("protected", f"keep {token!r} as it is")
    for key in _PRESS_KEY.findall(english):
        if not re.search(rf"(?<![\w+]){re.escape(key)}(?![\w+])", text):
            report("protected", f"keep the key {key!r}")
    english_keys = _key_bar(english)
    if english_keys is not None and _key_bar(text) != english_keys:
        report("keys", f"must read as the keys {english_keys} in the same order (an action starts with a plain "
                       f"letter: A-Z, a digit or '(')")
    if message.budget is not None and _cells(text) > message.budget:
        report("budget", f"{_cells(text)} cells, over the budget of {message.budget}")
    return problems


def glossary_problems(text: str, where: str, message: Message, glossary: dict) -> list[Problem]:
    problems, plain = [], _plain(text)
    for term in glossary["terms"]:
        if term.get("ctx"):
            if term["ctx"] == message.ctx and term["term"] == message.msgid and text != term["use"]:
                problems.append(Problem(where, "glossary", f"{message.key!r} is {term['use']!r} in the glossary"))
            continue
        scan = plain
        for phrase in term.get("allowed", []):  # set phrases that contain a forbidden word
            scan = re.sub(rf"(?<!\w){re.escape(phrase)}(?!\w)", " ", scan, flags=re.IGNORECASE)
        for pattern in term.get("forbidden", []):
            match = _forbidden(pattern).search(scan)
            if match:
                problems.append(Problem(where, "glossary", f"{match.group()!r}: the glossary says {term['term']} → "
                                                           f"{term['use']}"))
    for name in glossary["keep"]:
        within = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)")
        if within.search(message.msgid) and not within.search(text):
            problems.append(Problem(where, "glossary", f"keep the name {name!r} untranslated"))
    return problems


def entry_problems(message: Message, value, where: str, glossary: dict) -> list[Problem]:
    """Every problem of one catalogue entry, *value*, for *message*."""
    if message.plural is None:
        if not isinstance(value, str):
            return [Problem(where, "shape", "a plain message takes a string")]
        return pair_problems(message.msgid, value, where, message) + glossary_problems(value, where, message, glossary)
    if not isinstance(value, dict) or not {"one", "other"} <= set(value) or not set(value) <= set(i18n.PLURAL_FORMS) \
            or not all(isinstance(text, str) for text in value.values()):
        return [Problem(where, "shape", 'a counted message takes {"one": …, "other": …} and optionally "zero"')]
    problems = []
    for form, text in value.items():
        english = message.msgid if form == "one" else message.plural
        problems += pair_problems(english, text, where, message, form)
        problems += glossary_problems(text, where, message, glossary)
    return problems


def catalogue_problems(code: str, extraction: Extraction | None = None) -> list[Problem]:
    """Every problem of *code*'s catalogue against the code's messages."""
    extraction = extraction or extract()
    files, problems = load_files(code)
    glossary = load_glossary(code)
    seen: dict[str, tuple[str, object]] = {}
    for where, entries in files.items():
        for key, value in entries.items():
            spot = f"{where} {key!r}"
            if not unicodedata.is_normalized("NFC", key):
                problems.append(Problem(spot, "nfc", "the key is not in NFC"))
            if key in seen and seen[key][1] != value:
                problems.append(Problem(spot, "conflict", f"translated differently in {seen[key][0]}"))
            seen.setdefault(key, (where, value))
            message = extraction.messages.get(key)
            if message is None:
                problems.append(Problem(spot, "obsolete", "no code uses this message: remove it"))
                continue
            problems += entry_problems(message, value, spot, glossary)
    for key, message in sorted(extraction.messages.items()):
        if key not in seen:
            first = message.sites[0] if message.sites else "RESERVED"
            problems.append(Problem(f"{code} {key!r}", "missing", f"not translated (used at {first})"))
    return problems


def layout_problems() -> list[Problem]:
    """Locale folders and the shipped languages agree."""
    folders = {path.name for path in i18n.LOCALES.iterdir() if path.is_dir()} if i18n.LOCALES.is_dir() else set()
    problems = [Problem(_relative(i18n.LOCALES / name), "layout", "not a language in i18n.LANGUAGES")
                for name in sorted(folders - set(shipped()))]
    problems += [Problem(code, "layout", f"no folder {_relative(i18n.LOCALES / code)}")
                 for code in shipped() if code not in folders]
    return problems


def bare_problems(extraction: Extraction) -> list[Problem]:
    """Bare UI literals in the modules marked converted."""
    keep = all_kept()
    return [Problem(f"{relative}:{line}", "bare", f"{text!r} is UI text outside t(): convert it, or mark the line "
                                                   f"'# i18n: ignore'")
            for relative in extraction.converted for line, text in bare_literals(ROOT / relative, keep)]


def code_problems(extraction: Extraction | None = None) -> list[Problem]:
    extraction = extraction or extract()
    return extraction.problems + bare_problems(extraction)


def check(codes: list[str] | None = None) -> list[Problem]:
    """Every problem: the code's, the layout's and each language's catalogue."""
    extraction = extract()
    problems = code_problems(extraction) + layout_problems()
    for code in codes or shipped():
        problems += catalogue_problems(code, extraction)
    return problems


# --- commands --------------------------------------------------------------------------

def _context(site: Site, around: int = 2) -> list[str]:
    lines = (ROOT / site.file).read_text(encoding="utf-8").splitlines()
    first, last = max(1, site.line - around), min(len(lines), min(site.end, site.line + 6) + around)
    return [f"{'>' if site.line <= number <= site.end else ' '} {number:>5} | {lines[number - 1]}"
            for number in range(first, last + 1)]


def _matches(site: Site, files: list[str]) -> bool:
    return any(site.file == wanted or site.file.endswith("/" + wanted.lstrip("./")) for wanted in files)


def todo(code: str, files: list[str] | None = None) -> list[dict]:
    """The messages *code* lacks, each with its uses, code around them, budget and glossary terms."""
    extraction = extract()
    have = merged(code)
    glossary = load_glossary(code)
    files = [path.replace("\\", "/") for path in files or []]
    entries = []
    for key, message in sorted(extraction.messages.items(), key=lambda item: (
            item[1].sites[0].file if item[1].sites else "~", item[1].sites[0].line if item[1].sites else 0)):
        if key in have:
            continue
        sites = [site for site in message.sites if not files or _matches(site, files)]
        if files and not sites:
            continue
        entries.append({
            "key": key, "msgid": message.msgid, "ctx": message.ctx, "plural": message.plural,
            "placeholders": sorted(fields(message.msgid) or set()), "budget": message.budget,
            "sites": [{"file": site.file, "line": site.line, "function": site.function, "kind": site.kind,
                       "code": _context(site)} for site in sites],
            "glossary": [{key: term[key] for key in ("term", "use", "forbidden", "note", "ctx") if key in term}
                         for term in glossary_hits(message, glossary)],
        })
    return entries


def _print_todo(code: str, entries: list[dict]) -> None:
    if not entries:
        print(f"{code}: nothing to translate.")
        return
    print(f"{code}: {len(entries)} message(s) to translate. Add them to "
          f"{_relative(i18n.LOCALES / code)}/<file>.json (shared words in common.json); docs/i18n/{code}.md is "
          f"the style guide.\n")
    for entry in entries:
        print(f"== {entry['msgid']!r}" + (f"  (ctx {entry['ctx']!r})" if entry["ctx"] else ""))
        if entry["plural"] is not None:
            print(f"   plural: {entry['plural']!r}  -> give \"one\" and \"other\" (and \"zero\" if 0 reads better)")
        if entry["budget"] is not None:
            print(f"   budget: at most {entry['budget']} cells")
        for term in entry["glossary"]:
            avoid = f" (not {', '.join(term['forbidden'])})" if term.get("forbidden") else ""
            note = f": {term['note']}" if term.get("note") else ""
            print(f"   glossary: {term['term']} → {term['use']}{avoid}{note}")
        for site in entry["sites"]:
            print(f"   {site['file']}:{site['line']} in {site['function']} ({site['kind']})")
            for line in site["code"]:
                print(f"     {line}")
        print()
    skeleton = {entry["key"]: ({"one": "", "other": ""} if entry["plural"] is not None else "") for entry in entries}
    print("Skeleton:\n" + json.dumps(skeleton, ensure_ascii=False, indent=2))


def stats() -> list[str]:
    extraction = extract()
    languages = shipped()
    catalogues = {code: merged(code) for code in languages}
    by_module: dict[str, set] = {}
    for key, message in extraction.messages.items():
        for site in message.sites or [Site("(reserved)", 0, 0, "", "t")]:
            by_module.setdefault(site.file, set()).add(key)
    width = max([len("module")] + [len(name) for name in by_module]) + 2
    rows = [f"{'module':<{width}}{'messages':>9}" + "".join(f"{code:>12}" for code in languages)]
    for name in sorted(by_module):
        keys = by_module[name]
        rows.append(f"{name:<{width}}{len(keys):>9}"
                    + "".join(f"{sum(key in catalogues[code] for key in keys):>8}/{len(keys):<3}" for code in languages))
    known = set(extraction.messages)
    rows.append("")
    for code in languages:
        have = set(catalogues[code])
        rows.append(f"{code}: {len(known & have)} of {len(known)} translated, {len(known - have)} missing, "
                    f"{len(have - known)} obsolete")
    reused = [message.key for message in extraction.messages.values() if message.reserved and message.sites]
    rows.append(f"reserved: {len(RESERVED)} ({len(reused)} now used in code)")
    rows.append("converted modules: " + (", ".join(extraction.converted) or "none yet"))
    rows.append(f"dynamic t() calls: {len(extraction.dynamic)}")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interface translation tools.")
    commands = parser.add_subparsers(dest="command", required=True)
    extract_command = commands.add_parser("extract", help="list every message in the code")
    extract_command.add_argument("--json", action="store_true")
    todo_command = commands.add_parser("todo", help="what a language still lacks")
    todo_command.add_argument("language")
    todo_command.add_argument("--files", nargs="+", metavar="FILE")
    todo_command.add_argument("--json", action="store_true")
    check_command = commands.add_parser("check", help="run the catalogue and code checks")
    check_command.add_argument("language", nargs="?")
    commands.add_parser("stats", help="messages and translations per module")
    bare_command = commands.add_parser("bare", help="literals that look like UI text and reach no t()")
    bare_command.add_argument("files", nargs="+", metavar="FILE")
    args = parser.parse_args(argv)

    if args.command in ("todo", "check") and getattr(args, "language", None):
        code = i18n.normalise(args.language)
        if code not in shipped():
            parser.error(f"no catalogue for {args.language!r}: choose from {', '.join(shipped())}")
        args.language = code
    if args.command == "extract":
        extraction = extract(reserved=False)
        if args.json:
            print(json.dumps({"messages": [{"key": message.key, "msgid": message.msgid, "ctx": message.ctx,
                                            "plural": message.plural, "sites": [vars(site) for site in message.sites]}
                                           for message in extraction.messages.values()],
                              "dynamic": [{"site": vars(item.site), "expression": item.expression}
                                          for item in extraction.dynamic],
                              "problems": [vars(problem) for problem in extraction.problems]},
                             ensure_ascii=False, indent=2))
            return 0
        for message in extraction.messages.values():
            label = repr(message.msgid) + (f" / {message.plural!r}" if message.plural is not None else "")
            print(label + (f"  (ctx {message.ctx!r})" if message.ctx else ""))
            for site in message.sites:
                budget = f", budget {site.budget}" if site.budget is not None else ""
                print(f"    {site} in {site.function} ({site.kind}{budget})")
        for item in extraction.dynamic:
            print(f"dynamic: {item.site} in {item.site.function}: {item.site.kind}({item.expression})")
        for problem in extraction.problems:
            print(f"problem: {problem}")
        print(f"\n{len(extraction.messages)} message(s), {len(extraction.dynamic)} dynamic call(s), "
              f"{len(extraction.problems)} problem(s)")
        return 0
    if args.command == "todo":
        entries = todo(args.language, args.files)
        if args.json:
            print(json.dumps(entries, ensure_ascii=False, indent=2))
        else:
            _print_todo(args.language, entries)
        return 0
    if args.command == "check":
        problems = check([args.language] if args.language else None)
        for problem in problems:
            print(problem)
        print(f"{len(problems)} problem(s)" if problems else "No problems.")
        return 1 if problems else 0
    if args.command == "stats":
        print("\n".join(stats()))
        return 0
    keep = all_kept()
    for name in args.files:
        path = Path(name).resolve()
        for line, text in bare_literals(path, keep):
            print(f"{_relative(path)}:{line}: {text!r}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
