"""The prose rules the linter cannot state, over code and documents alike.

`W505` fails a doc line that runs past `max-doc-length`. Nothing fails one left
too *short* — and that is the shape an in-place edit leaves behind, because
substituting a word inside a wrapped paragraph pushes the overflow onto its own
line instead of reflowing the block. The formatter never reflows prose, so the
result survives format, lint, type check, and the whole suite.

Three rules answer that, and three coverage guards keep each rule's walk honest.
A document soft-wraps instead, one line per paragraph (ADR 0040), so a later
diff shows the sentence that changed rather than the reflow around it. A word
scan holds code and documents alike to the American spelling (ADR 0041) — that
rule is the one that reads both formats, while the one-line rule reads only
markdown.

The stranded rule is exact rather than a guess about raggedness: a line is
stranded when it stopped short of the wrap width while the next line still held
a word that would have fit. A paragraph's last line is exempt — that is where
prose ends, not where it was abandoned. Comments and docstrings differ only in
how prose is found, so what counts as stranded is asked in one place.

The guards share one strip of what the rules do not govern. A fenced block, a
code span, a URL, and a Python literal that is not a docstring all hold names
another system chose, so they come out before any rule reads the line, and both
markdown rules read one definition of that region rather than each keeping its
own. Frontmatter is the exception the two rules part company on, and the region
function takes it as an argument for that reason: a `description:` is prose a
person reads, so the spelling rule scans it, while it is one YAML line no editor
can reflow, so the one-line rule never sees it.

Neither the width nor the walked roots is written into the rules here. Both are
read from the linter's own settings, so a rule cannot drift out of step with the
check it pairs with and leave a band of lines that neither one reaches. The
numbers the coverage guards assert are drift alarms on that derivation, not the
derivation itself.

See `.claude/skills/code-documentation/SKILL.md` ("Shape the guards check")
for the rewrap rule a failure here asks for.
"""

import ast
import re
import subprocess
import tomllib
from collections.abc import Collection
from fnmatch import fnmatch
from functools import cache
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def _repo_name(path: Path) -> str:
    """A path as the repo names it, so an offender reads as somewhere to go."""
    return path.relative_to(_REPO).as_posix()


@cache
def _ruff_config() -> dict:
    """The linter's own settings. Both the width these rules wrap to and the
    files they skip are its decisions, read here rather than restated."""
    return tomllib.loads((_REPO / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]


def _ruff_setting(*keys: str):
    """One setting out of the linter's config, or a failure that names the key.

    Every reader here indexes a nested path that a config reshuffle can move.
    Indexing it directly raises a bare `KeyError` naming one fragment, which at
    module scope aborts collection for the whole file and takes the drift guard
    written to catch exactly this down with it. Naming the path and the file it
    was read from turns that into a diagnosis.
    """
    found = _ruff_config()
    for index, key in enumerate(keys):
        if not isinstance(found, dict) or key not in found:
            path = ".".join(("tool", "ruff", *keys[: index + 1]))
            raise AssertionError(f"pyproject.toml has no [{path}]; these prose rules read it")
        found = found[key]
    return found


def _max_doc_length() -> int:
    """The linter's own prose width, read rather than copied.

    `W505` fails a doc line past this; the rules here fail one left short of it.
    A width duplicated in both places drifts the day one of them moves, and the
    drift is invisible — every line in the gap passes both checks.
    """
    return _ruff_setting("lint", "pycodestyle", "max-doc-length")


# The width prose wraps to. One under `max-doc-length`, so a line filled to the
# limit still reads as full rather than as one word short of the check.
WRAP = _max_doc_length() - 1

# Below this a line is short enough that stopping there needs a reason. The
# repo's blocks sit in a flat region either side of it — every nearby threshold
# agrees on them — so the value is a floor, not a boundary anything balances on.
# It carries no count: the last one described a tree two rewraps ago.
STRANDED = 65

# Line breaks these own are structural — a list item, a doctest, an argument or
# `Raises:` block — so joining them onto the previous line would be wrong rather
# than tidier.
_STRUCTURED = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s|>>>|:param|:return|Raises:|Args:|Returns:|\|")

# A URL or pragma cannot be broken and cannot move, so a line ending short of
# one is the wrap doing its best. `W505` exempts these for the same reason.
_UNBREAKABLE = re.compile(r"https?://|noqa|ty:\s*ignore|type:\s*ignore")


def _prose_on_line(line: str) -> str:
    return line.strip().removeprefix("#").strip('"').strip()


def stranded_line(paragraph: list[str]) -> int | None:
    """Index of the first line that stopped short while the next line still had
    a word that would have fit, or None when the paragraph is well wrapped.

    `paragraph` is the raw source lines, prefix and indent included — the width
    being judged is the one a reader sees, which is why a docstring's opening
    quotes count toward its first line.
    """
    for index, (line, following) in enumerate(zip(paragraph, paragraph[1:], strict=False)):
        words = _prose_on_line(following).split()
        if not words:
            continue
        if len(line) < STRANDED and len(line) + 1 + len(words[0]) <= WRAP:
            return index
    return None


def _paragraphs(lines: list[str], first_line: int) -> list[tuple[int, list[str]]]:
    """Runs of prose split on the blank line between one thought and the next,
    each paired with the file line its first line sits on.

    A line holding only quotes reads as blank: it closes a docstring rather than
    continuing its last sentence. Single-line runs drop out — a lone line has no
    following line to have stranded it. `first_line` is where `lines` starts in
    the file, so an offender can be reported as somewhere to go rather than as a
    snippet the reader has to search for.
    """
    found: list[tuple[int, list[str]]] = []
    current: list[str] = []
    start = first_line
    for offset, line in enumerate(lines):
        if _prose_on_line(line):
            if not current:
                start = first_line + offset
            current.append(line)
        elif current:
            found.append((start, current))
            current = []
    if current:
        found.append((start, current))
    return [(at, p) for at, p in found if len(p) > 1]


def _is_prose(paragraph: list[str]) -> bool:
    # Structure is judged on the text, not the raw line — a `#` or a `"""` sits
    # where a list marker's own anchor would otherwise match. Unbreakables are
    # judged on the raw line, since a URL can appear anywhere in it.
    return not any(_STRUCTURED.search(_prose_on_line(line)) or _UNBREAKABLE.search(line) for line in paragraph)


def comment_paragraphs(source: str) -> list[tuple[int, list[str]]]:
    """Prose paragraphs of every run of standalone comment lines at one indent,
    each paired with the file line it starts on.

    Trailing comments are excluded: they sit at whatever column their code
    leaves them and are not wrapped prose. The indent has to match for a run to
    continue, so a module-level block and an indented one inside a function stay
    two paragraphs — merging them would judge raggedness across a seam no reader
    sees, and a structural line on either side of it would drop both.
    """
    paragraphs: list[tuple[int, list[str]]] = []
    lines = source.splitlines()
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("#"):
            index += 1
            continue
        indent = len(lines[index]) - len(lines[index].lstrip())
        block: list[str] = []
        started = index
        while (
            index < len(lines)
            and lines[index].lstrip().startswith("#")
            and len(lines[index]) - len(lines[index].lstrip()) == indent
        ):
            block.append(lines[index])
            index += 1
        paragraphs.extend((at, p) for at, p in _paragraphs(block, started + 1) if _is_prose(p))
    return paragraphs


def docstring_paragraphs(source: str) -> list[tuple[int, list[str]]]:
    """Prose paragraphs of every module, class, and function docstring, each
    paired with the file line it starts on.

    Read off the source lines rather than the parsed string value, because the
    indent and the opening quotes are part of the width a reader sees. Only the
    docstring position counts — a triple-quoted string used as a value is data,
    and wrapping it would change it.
    """
    lines = source.splitlines()
    paragraphs: list[tuple[int, list[str]]] = []
    for node in _docstring_constants(ast.parse(source)):
        if not isinstance(node.value, str) or node.end_lineno is None:
            continue
        spanned = lines[node.lineno - 1 : node.end_lineno]
        paragraphs.extend((at, p) for at, p in _paragraphs(spanned, node.lineno) if _is_prose(p))
    return paragraphs


def _docstring_constants(tree: ast.Module) -> list[ast.Constant]:
    """Every docstring in `tree`, as the constant node holding it.

    Two guards need the same answer — the paragraph rule reads the lines a
    docstring spans, and the spelling strip has to leave those literals alone
    while blanking every other one. Two spellings of "is this a docstring"
    would drift, and the drift would blank prose one rule still reads.
    """
    return [
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    ]


# A fence opens or closes a code block. The lines between are code, and their
# breaks are the code's own — joining them would change what they run. The
# delimiter is captured because a `~~~` line does not close a ``` block, and a
# toggle that took it for one would read the code below as prose.
_FENCE = re.compile(r"^\s*(```+|~~~+)")

# Frontmatter opens with `---` on line 1 — but so does a document whose first
# element is a thematic break. A mapping key on the line below tells the two
# apart. Without it the closing search runs to the next `---` anywhere in the
# document, and everything above it is blanked out of both rules.
_FRONTMATTER_KEY = re.compile(r"[\w-]+\s*:")

# A quoted line, and the hard break that says the author meant it to end there.
# Consecutive `>` lines are the one case a block marker cannot settle, because
# the ask block writes every quoted line with its own `>`; the break is what
# separates that shape from one quote wrapped across several lines.
_QUOTE = re.compile(r"^\s*>+\s?")
_HARD_BREAK = re.compile(r"(?:  |\\)$")

# A heading, a table row, and a thematic break each end at their own line break,
# so the line under one opens a new block instead of continuing it.
_CLOSED_BLOCK = r"#{1,6}\s|\||-{3,}\s*$|={3,}\s*$"

# A bullet, a quote, or an HTML tag opens a block a later line can still be a
# lazy continuation of.
_OPEN_BLOCK = r"[-*+]\s|>|\d+[.)]\s|<"

# Every block opener, closed and open alike: joining one to the line above would
# merge two blocks rather than repair one that was wrapped. Composed from the
# two names above so a new form is added once, not to two patterns that must
# agree.
_BLOCK_START = re.compile(rf"^\s*(?:{_OPEN_BLOCK}|{_CLOSED_BLOCK})")
_UNCONTINUABLE = re.compile(rf"^\s*(?:{_CLOSED_BLOCK})")


def _markdown_body(document: str, *, keep_frontmatter: bool) -> str:
    """`document` reduced to the region the markdown rules govern: fenced code
    blanked, frontmatter kept or dropped as the caller says, line numbers kept.

    One definition of that region. What runs inside a fence belongs to another
    system, so no rule here reads it.

    The two rules part company on frontmatter, which is why the caller says.
    A `description:` is prose a person reads, so the standard spells it; it is
    also one YAML line that cannot be reflowed, so the wrap rule leaves it
    alone. That difference is a decision, and stating it at each call site is
    what keeps it from drifting back into two private answers.
    """
    lines = document.splitlines()
    opening = 0
    if not keep_frontmatter and len(lines) > 1 and lines[0].strip() == "---" and _FRONTMATTER_KEY.match(lines[1]):
        closing = next((n for n in range(1, len(lines)) if lines[n].strip() == "---"), None)
        if closing is not None:
            opening = closing + 1

    body = ["" for _ in range(opening)]
    opened: str | None = None
    for line in lines[opening:]:
        fence = _FENCE.match(line)
        if fence and opened is None:
            opened = fence.group(1)
            body.append("")
        elif fence and opened is not None and line.strip().startswith(opened):
            opened = None
            body.append("")
        else:
            body.append("" if opened else line)
    return "\n".join(body)


def unclosed_fence(document: str) -> int | None:
    """The line a fence opens on and never closes, or None when every fence in
    `document` is matched.

    Worth its own answer because the blanking cannot give one: an unterminated
    fence blanks every line below it, and a blanked line is indistinguishable
    from a blank one, so both markdown rules would go quiet over the rest of the
    document and report the same clean result as a document that had nothing
    wrong with it.
    """
    opened: str | None = None
    opened_at: int | None = None
    for number, line in enumerate(document.splitlines(), start=1):
        fence = _FENCE.match(line)
        if not fence:
            continue
        if opened is None:
            opened, opened_at = fence.group(1), number
        elif line.strip().startswith(opened):
            opened, opened_at = None, None
    return opened_at


def markdown_continuations(document: str) -> list[int]:
    """Line numbers of every line that continues the block above it — the hard
    wrap ADR 0040 rules out.

    A block is a paragraph, a bullet, or a blockquote line, and it ends where
    its own line does.

    A quoted line is judged against the quoted line above it rather than against
    a block marker, because every line of an ask block carries its own `>` and a
    marker cannot tell that shape from one quote wrapped across several lines. A
    markdown hard break is what an author writes to mean the line ends here, so
    a quoted line under one that carries no break is a wrapped quote. A bare `>`
    separates two quoted paragraphs and continues neither.
    """
    found: list[int] = []
    continuable = False
    quoted_unbroken = False
    for number, line in enumerate(_markdown_body(document, keep_frontmatter=False).splitlines(), start=1):
        if not line.strip():
            continuable = False
            quoted_unbroken = False
            continue
        quote = _QUOTE.match(line)
        inner = line[quote.end() :] if quote else ""
        wrapped_quote = bool(quote) and quoted_unbroken and bool(inner.strip()) and not _BLOCK_START.match(inner)
        wrapped_block = not quote and continuable and not _BLOCK_START.match(line)
        if wrapped_quote or wrapped_block:
            found.append(number)
        continuable = not _UNCONTINUABLE.match(line)
        quoted_unbroken = bool(quote and inner.strip()) and not _HARD_BREAK.search(line)
    return found


# A glossary entry: the bolded term in the first cell and its definition in the
# second. The header and separator rows carry no bolded term, so the pattern
# passes over them without naming them, and the aliases cell sits outside the
# match because a list of words to avoid is not a definition and carries no
# ceiling. The definition cell stops at the next `|` rather than running to the
# end of the line, which is what keeps the aliases out of the count.
_TERM_ROW = re.compile(r"^\|\s*\*\*(?P<term>[^*]+)\*\*\s*\|(?P<definition>[^|]*)\|")

# The ceiling on one glossary definition, in words. A definition says what the
# term is; the mechanism behind it belongs to the record that owns it, and the
# failure this number catches is that mechanism creeping back into the glossary
# one clause at a time. Anchored on the pruned file, whose longest definition is
# 94 words: close enough that the ceiling still binds, far enough that no entry
# sits one edit from red.
#
# Words, not sentences, because the sentence split a regex can do passes cells a
# reader fails — a 74-word single sentence is over any cap a reader would set —
# and doing better means understanding "e.g.", "2.1 AA", and a code span with a
# period inside it. Counted by whitespace, the same way the audit that set the
# number counted, so its figures reproduce here rather than needing conversion.
DEFINITION_WORDS = 100


def glossary_definitions(document: str) -> list[tuple[int, str, str]]:
    """Every term row of the glossary, as line number, term, and definition.

    Fenced code is blanked first: a table drawn inside a fence is an example of
    the shape rather than an entry, and holding an example to the ceiling would
    fail a document for explaining the rule.
    """
    return [
        (number, match["term"], match["definition"].strip())
        for number, line in enumerate(_markdown_body(document, keep_frontmatter=False).splitlines(), start=1)
        if (match := _TERM_ROW.match(line))
    ]


def definitions_over_ceiling(document: str) -> list[tuple[int, str, int]]:
    """Every definition past the ceiling, as line number, term, and word count.

    Separate from the guard that reads `DOMAIN.md` so the boundary itself can be
    put under test. A rule whose only subject is one real file is green whenever
    that file is clean, which says nothing about where it turns red.
    """
    return [
        (number, term, count)
        for number, term, definition in glossary_definitions(document)
        if (count := len(definition.split())) > DEFINITION_WORDS
    ]


# Copied from `british_words` in the skills repo's `scripts/lint-skills.sh`,
# in that file's order so a drifted copy diffs cleanly against it. A word joins
# or leaves the standard there, never here (ADR 0041).
BRITISH_WORDS = frozenset(
    """
    behaviour behaviours colour colours coloured favour favours favoured favourite labour honour humour
    neighbour neighbours rumour endeavour flavour centre centres fibre litre metre metres theatre licence
    licences defence offence pretence analyse analysed analysing paralyse organise organised organises
    organising organisation recognise recognised recognises recognising prioritise prioritised prioritises
    prioritising summarise summarised summarises summarising synthesise synthesised synthesises synthesising
    minimise minimised minimises minimising maximise maximised maximises maximising normalise normalised
    normalises normalising serialise serialised serialises serialising initialise initialised initialises
    initialising utilise utilised utilises utilising categorise categorised categorises categorising emphasise
    emphasised emphasises emphasising apologise apologised apologises apologising optimise optimised optimises
    optimising optimisation specialise specialised standardise standardised generalise generalised formalise
    formalised realise realised realises realising criticise criticised memorise memorised characterise
    characterised itemise itemised harmonise harmonised tokenise tokenised tokenises tokenising tokeniser
    tokenisation cancelled cancelling modelling labelling labelled travelled travelling signalled fulfil
    fulfilment enrolment instalment whilst amongst grey artefact artefacts sceptic sceptical scepticism
    programme programmes judgement judgements acknowledgement acknowledgements storey draught practise
    practised enquire enquiry authorise authorised authorises authorising authorisation authorisations
    neighbouring neighbourhood neighbourhoods catalogue catalogues catalogued cataloguing generalises
    generalising generalisation generalisations standardises standardising standardisation honours honoured
    honouring honourable flavours flavoured flavouring favourable favourably favourites labours laboured
    labouring humours rumours endeavours endeavoured endeavouring fibres litres defences offences pretences
    organisations optimisations specialises specialising specialisation formalises formalising criticises
    criticising memorises memorising characterises characterising itemises itemising harmonises harmonising
    realisation realisations prioritisation categorisation normalisation serialisation initialisation
    utilisation minimisation maximisation summarisation paralysed paralyses paralysing modelled signalling
    fulfils enrolments instalments judgemental draughts sceptics storeys enquires enquired enquiries practises
    practising tokenisers behavioural behaviourally colourful colouring manoeuvre manoeuvres manoeuvring mould
    moulds moulded counselling counsellor counsellors centred centring licenced
    """.split()  # noqa: SIM905 — upstream's order and shape, so a drifted copy diffs cleanly
)

# A British form some other system matches by string, mapped to the consumer
# that requires it. An entry with no named consumer is a word someone did not
# want to change, which is the thing the standard exists to settle (ADR 0041).
# Keyed by the file the consumer sits in, because that is what 0041 names. A
# bare word would excuse the plain English form everywhere — this one entry
# would quietly permit `cancelled` in every document in the repo.
DELIBERATE_BRITISH = {
    ("tests/cli/conftest.py", "Cancelled"): "CPython's `asyncio.CancelledError`, reached by import",
}


# The same one-literal rule as the spelling failure below, for the same reason:
# the number is left out so the sentence stays one line, and the offender rows
# carry each cell's own count anyway.
_CEILING_FAILURE = "Glossary definitions run past the word ceiling. Move the mechanism to the record that owns it, and leave the definition:\n"  # noqa: E501


# The failure a developer pastes into a search. It is one literal on one line,
# because implicit concatenation renders as one sentence at failure time and
# greps to nothing: the line the reader copies has to be the line they find.
# The line-length suppression below is there for the same reason — a join to
# get under the limit would put the sentence back beyond reach of a search.
_SPELLING_FAILURE = "British spellings in prose this repo owns. Write the American form, or add the word to DELIBERATE_BRITISH keyed by the file whose consumer matches it by string (ADR 0041):\n"  # noqa: E501


def roster_exemptions(name: str) -> frozenset[str]:
    """The words the roster excuses in this file, and in no other.

    The key is matched exactly, not as a glob. A pattern key would put `*` back
    within reach, and a single `("*", "Cancelled")` entry excuses the everyday
    spelling in every document in the repo — the failure ADR 0041's file key was
    added to prevent. Exact matching also keeps a real filename holding `[`, `?`
    or `*` matching its own entry.
    """
    return frozenset(word for path, word in DELIBERATE_BRITISH if name == path)


# A name another system chose. Neither is this repo's prose to spell, so both
# come out before the lookup rather than being excused after it.
_CODE_SPAN = re.compile(r"`[^`]*`")
_URL = re.compile(r"https?://\S*")

# Words as a reader reads them, identifiers included: `CancelledError` is two.
# A scan stopping at identifier boundaries never reaches the form inside one.
#
# An all-caps run is not read as a word, so `BEHAVIOUR` and `COLOUR_MAP` pass:
# one capital followed by lowercase is the shape, and widening it to admit a
# second capital would flag every acronym in the repo. The gap is left open
# deliberately and stated here because nothing else in the tree would say so —
# a SCREAMING_CASE constant, an enum member, or an env-var name carrying a
# British form is invisible to this rule.
_WORD = re.compile(r"[A-Za-z][a-z]*")


def british_spellings(text: str, *, exempt: Collection[str] = ()) -> list[str]:
    flagged = BRITISH_WORDS - {word.lower() for word in exempt}
    stripped = _URL.sub(" ", _CODE_SPAN.sub(" ", text))
    return [word for word in _WORD.findall(stripped) if word.lower() in flagged]


def _without_literals(source: str) -> str:
    """`source` with every string constant that is not a docstring blanked out.

    This repo's prose in Python is its comments and its docstrings. A bare
    literal is data — a word list, a test fixture, an upstream state value —
    and gets the carve-out a code span gets in markdown. An identifier is not
    stripped, which is why `CancelledError` still needs its roster entry.

    Line numbers survive, so an offender still reports where it is. So does
    line content, which is why the blanking runs over the encoded line rather
    than the decoded one: `col_offset` and `end_col_offset` are UTF-8 byte
    offsets, and this repo's prose is dense with em dashes, so slicing a `str`
    with them shifts the window by one position per non-ASCII character to the
    left of the literal. Both directions corrupt the scan — over-blanking eats
    the trailing comment a rule was meant to read, and under-blanking exposes a
    fragment whose only escape would be a roster entry.
    """
    tree = ast.parse(source)
    encoded = [line.encode() for line in source.splitlines()]
    documented = {id(node) for node in _docstring_constants(tree)}
    literals = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in documented
    ]
    for node in sorted(literals, key=lambda n: (n.lineno, n.col_offset), reverse=True):
        end_line, end_column = node.end_lineno, node.end_col_offset
        if end_line is None or end_column is None:
            continue
        for number in range(node.lineno - 1, end_line):
            start = node.col_offset if number == node.lineno - 1 else 0
            stop = end_column if number == end_line - 1 else len(encoded[number])
            encoded[number] = encoded[number][:start] + b" " * (stop - start) + encoded[number][stop:]
    return "\n".join(line.decode() for line in encoded)


def spellable_lines(name: str, text: str) -> list[str]:
    """The lines of `text` the spelling standard governs, by file format.

    A format with no extractor here yields nothing rather than everything. The
    walk covers every tracked file, and a lockfile, a generated contract, and a
    captured axe payload fixture all hold names another system chose; reading
    them as prose would leave a roster entry as the only way to quiet one.
    """
    if name.endswith(".py"):
        return _without_literals(text).splitlines()
    if name.endswith(".md"):
        return _markdown_body(text, keep_frontmatter=True).splitlines()
    return []


def _file_text(path: Path) -> str | None:
    """The file as text, or None where it holds bytes rather than prose.

    The encoding is named rather than taken from the locale, so a machine whose
    locale is neither UTF-8 nor C decodes this repo's em dashes the same way CI
    does instead of silently substituting replacement characters. The `except`
    is narrow for the same reason: a `PermissionError` or a directory handed in
    by mistake is a real failure, and returning None for it would file that
    failure under "this file is binary" and leave nothing to notice.
    """
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError, FileNotFoundError:
        return None


@cache
def _tracked(pattern: str) -> tuple[Path, ...]:
    """Paths git tracks, so an ignored working directory — a local review
    report, a virtualenv, a build tree — never counts as this repo's prose.

    `-z` because git C-quotes a path holding non-ASCII bytes otherwise, and the
    quoted spelling names no file on disk. A missing `git`, or a tree that is
    not a checkout, fails here with what these rules were trying to read: an
    `rglob` fallback would answer a different question — every file rather than
    every tracked file — which is the whole reason the walk asks git at all.
    """
    try:
        listed = subprocess.run(
            ["git", "-C", str(_REPO), "ls-files", "-z", pattern],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as failure:
        raise AssertionError(f"the prose rules read `git ls-files` and it failed: {failure}") from failure
    return tuple(_REPO / name for name in listed.stdout.split("\0") if name)


def _w505_exemptions() -> list[str]:
    """The globs the linter excuses from `W505`, so these rules excuse them too.

    A rule that failed a file the linter passes would have no edit that
    satisfies both. Both of ruff's per-file tables are read, and a code counts
    as a match when it is a prefix of `W505` — `["W"]` and `["ALL"]` disable the
    rule as surely as naming it does. `# ruff: noqa` and `exclude` are still
    unread: resolving those means re-implementing ruff, and the gap is stated
    here rather than half-closed.
    """
    tables = ("per-file-ignores", "extend-per-file-ignores")
    lint = _ruff_setting("lint")
    return [
        glob
        for table in tables
        for glob, codes in lint.get(table, {}).items()
        if any(code == "ALL" or "W505".startswith(code) for code in codes)
    ]


def _walked_sources() -> list[Path]:
    """Every tracked Python file `W505` reaches.

    The linter runs from the repo root, so the roots follow from what git
    tracks rather than from a list kept here — an enumerated pair went stale
    the moment a fourth tree grew, and the export script and the migration
    environment module sat outside it unchecked.

    A separator-free glob is matched against the basename as well as the
    repo-relative path, because that is what ruff does with one: a
    `"conftest.py"` entry exempts every conftest in the tree, and matching only
    the full path would fail files the linter passes.
    """
    exempt = _w505_exemptions()

    def excused(path: Path) -> bool:
        name = _repo_name(path)
        return any(fnmatch(name, glob) or ("/" not in glob and fnmatch(path.name, glob)) for glob in exempt)

    return sorted(path for path in _tracked("*.py") if not excused(path))


def _prose_documents() -> list[Path]:
    """Every markdown document ADR 0040 governs.

    The set is every tracked `.md` rather than an enumerated list of roots: a
    document added under a new directory is prose the day it lands, and a list
    would silently stop covering it.
    """
    return sorted(_tracked("*.md"))


def _prose_paragraphs() -> list[tuple[Path, int, list[str]]]:
    return [
        (path, at, paragraph)
        for path in _walked_sources()
        for source in [_file_text(path)]
        if source is not None
        for at, paragraph in comment_paragraphs(source) + docstring_paragraphs(source)
    ]


class TestStrandedLine:
    def test_line_that_could_have_taken_the_next_word_is_stranded(self) -> None:
        assert stranded_line(["# can only under-report declarations, so it fails loud. A", "# router mounted"]) == 0

    def test_well_wrapped_paragraph_is_not(self) -> None:
        paragraph = [
            "# Rollup-race 409s never fire organically in endpoint tests, so the",
            "# shim can't catch a missing concurrent_rollup declaration at all.",
        ]
        assert stranded_line(paragraph) is None

    def test_short_final_line_is_where_prose_ends(self) -> None:
        # The exemption that makes the rule usable: every paragraph ends short
        # of the width, and that is not a defect.
        paragraph = ["# a paragraph whose opening line is filled about as far as it will go", "# and short."]
        assert stranded_line(paragraph) is None

    def test_line_kept_short_by_a_word_that_could_not_fit_is_not_stranded(self) -> None:
        # Greedy wrapping already did its best; the next word is simply too
        # long. Flagging this would make the rule unsatisfiable.
        paragraph = ["# semantics live at the service seam", f"# ({'x' * 60})"]
        assert stranded_line(paragraph) is None

    def test_a_next_word_that_lands_exactly_on_the_width_is_stranded(self) -> None:
        # The boundary the `<= WRAP` comparison turns on. Flipping it to `<`
        # is the classic greedy-wrap off-by-one, and without this pair nothing
        # in the repo notices.
        short = "# " + "x" * 50
        assert len(short) == 52
        assert stranded_line([short, "# " + "y" * 26]) == 0
        assert stranded_line([short, "# " + "y" * 27]) is None

    def test_docstring_opening_quotes_count_toward_the_first_line(self) -> None:
        # The reader sees the quotes, so the width does too — otherwise an
        # opening line would get three free columns the rule never checks.
        assert stranded_line(['    """Resolve a matched route to the view', "    the document is generated from."]) == 0


class TestCommentParagraphs:
    def test_bare_hash_separates_paragraphs(self) -> None:
        source = "# first paragraph line one\n# ends here.\n#\n# second paragraph begins\n# and ends.\n"
        assert len(comment_paragraphs(source)) == 2

    def test_structural_and_unbreakable_blocks_are_excluded(self) -> None:
        assert comment_paragraphs("# - a list item\n# - another item\n") == []
        assert comment_paragraphs("# see\n# https://example.com/very/long/path\n") == []

    def test_trailing_comments_are_not_prose(self) -> None:
        assert comment_paragraphs("x = 1  # trailing\ny = 2  # also trailing\n") == []

    def test_blocks_at_different_indents_stay_separate_paragraphs(self) -> None:
        # What the indent-equality condition buys. Merged, the two blocks would
        # be judged as one paragraph across a seam no reader sees — and a
        # structural line on either side of it would then drop both.
        source = (
            "def f():\n"
            "    # an indented line that runs on far enough to matter here.\n"
            "    # and its tail.\n"
            "# - a list item at column zero\n"
            "# - another one\n"
        )
        assert len(comment_paragraphs(source)) == 1

    def test_a_paragraph_reports_the_file_line_it_starts_on(self) -> None:
        source = "x = 1\n\n# a comment paragraph opening here\n# and continuing here.\n"
        at, paragraph = comment_paragraphs(source)[0]
        assert at == 3
        assert len(paragraph) == 2


class TestDocstringParagraphs:
    def test_module_class_and_function_docstrings_are_all_read(self) -> None:
        source = (
            '"""Module line one\nmodule line two."""\n\n'
            'class C:\n    """Class line one\n    class line two."""\n\n'
            '    def m(self):\n        """Method line one\n        method line two."""\n'
        )
        assert len(docstring_paragraphs(source)) == 3

    def test_closing_quotes_on_their_own_line_do_not_extend_the_paragraph(self) -> None:
        # Otherwise the last prose line always looks stranded by a line that
        # holds no word at all.
        source = '"""A summary line filled out far enough that nothing more would fit\nand a short tail.\n"""\n'
        at, paragraph = docstring_paragraphs(source)[0]
        assert at == 1
        assert len(paragraph) == 2
        assert stranded_line(paragraph) is None

    def test_argument_and_raises_blocks_are_excluded(self) -> None:
        assert (
            docstring_paragraphs('def f():\n    """Do it.\n\n    Raises:\n        ValueError: when.\n    """\n') == []
        )

    def test_a_triple_quoted_value_is_not_a_docstring(self) -> None:
        assert docstring_paragraphs('SQL = """select 1\nfrom t"""\n') == []


class TestMarkdownContinuations:
    def test_a_wrapped_paragraph_reports_its_continuation(self) -> None:
        assert markdown_continuations("A paragraph that was hard\nwrapped here.\n") == [2]

    def test_a_one_line_paragraph_is_clean(self) -> None:
        assert markdown_continuations("A paragraph on one line.\n\nAnd another.\n") == []

    def test_consecutive_bullets_each_start_their_own_block(self) -> None:
        assert markdown_continuations("- first item\n- second item\n") == []

    def test_a_wrapped_bullet_reports_its_continuation(self) -> None:
        assert markdown_continuations("- an item that was hard\n  wrapped here.\n") == [2]

    def test_quoted_lines_ending_in_a_hard_break_each_start_their_own_block(self) -> None:
        # The ask-block shape: every line carries its own `>` and ends in a hard
        # break, which is the author saying the line ends there rather than
        # being wrapped. Without the break there is nothing to tell the two
        # apart, so the break is what the rule reads.
        assert markdown_continuations("> first line  \n> second line\n") == []

    def test_quoted_lines_without_a_hard_break_are_a_wrapped_quote(self) -> None:
        assert markdown_continuations("> a quote that was hard\n> wrapped here.\n") == [2]

    def test_a_bare_quote_marker_separates_two_quoted_paragraphs(self) -> None:
        # A `>` holding no text ends the quoted line above it, so the line below
        # opens its own block and continues nothing.
        assert markdown_continuations("> first paragraph\n>\n> second paragraph\n") == []

    def test_a_quoted_bullet_is_its_own_block(self) -> None:
        assert markdown_continuations("> - first item\n> - second item\n") == []

    def test_a_lazily_continued_blockquote_is_reported(self) -> None:
        assert markdown_continuations("> a quote that was hard\nwrapped here.\n") == [2]

    def test_a_blockquote_after_a_paragraph_is_not_a_continuation_of_it(self) -> None:
        assert markdown_continuations("A paragraph on one line.\n> a quote under it.\n") == []

    def test_fenced_code_keeps_its_own_line_breaks(self) -> None:
        assert markdown_continuations("```\nx = 1\ny = 2\n```\n") == []

    def test_prose_after_a_closing_fence_is_not_a_continuation_of_the_code(self) -> None:
        assert markdown_continuations("- item\n\n  ```\n  x = 1\n  ```\n  Trailing prose.\n") == []

    def test_text_under_a_heading_is_not_a_continuation_of_it(self) -> None:
        assert markdown_continuations("## A heading\nIts first paragraph.\n") == []

    def test_table_rows_are_their_own_lines(self) -> None:
        assert markdown_continuations("| a | b |\n| - | - |\n| 1 | 2 |\n") == []

    def test_frontmatter_is_not_prose(self) -> None:
        assert markdown_continuations("---\nname: x\ndescription: y\n---\n\nBody.\n") == []

    def test_every_continuation_of_a_three_line_paragraph_is_reported(self) -> None:
        assert markdown_continuations("one\ntwo\nthree\n") == [2, 3]


class TestGlossaryDefinitions:
    def test_a_term_row_yields_its_term_and_definition(self) -> None:
        row = "| **Slug** | A URL-friendly identifier for an app. | Key, code, handle |"
        assert glossary_definitions(row) == [(1, "Slug", "A URL-friendly identifier for an app.")]

    def test_the_header_and_separator_rows_are_not_entries(self) -> None:
        assert glossary_definitions("| Term | Definition | Aliases to avoid |\n| --- | --- | --- |") == []

    def test_a_row_reports_the_file_line_it_sits_on(self) -> None:
        document = "# Ubiquitous Language\n\n| **App** | A web application. | Site |"
        assert glossary_definitions(document) == [(3, "App", "A web application.")]

    def test_the_aliases_cell_is_not_counted_as_definition(self) -> None:
        row = "| **App** | Two words. | one two three four five six seven |"
        assert glossary_definitions(row) == [(1, "App", "Two words.")]

    def test_a_table_inside_a_fence_is_an_example_rather_than_an_entry(self) -> None:
        assert glossary_definitions("```\n| **App** | A web application. | Site |\n```") == []


class TestDefinitionsOverCeiling:
    @staticmethod
    def _row(words: int) -> str:
        return f"| **Term** | {'word ' * words}| alias |"

    def test_a_definition_one_word_past_the_ceiling_is_reported(self) -> None:
        assert definitions_over_ceiling(self._row(101)) == [(1, "Term", 101)]

    def test_a_definition_at_the_ceiling_is_not(self) -> None:
        assert definitions_over_ceiling(self._row(100)) == []

    def test_a_definition_one_word_under_the_ceiling_is_not(self) -> None:
        assert definitions_over_ceiling(self._row(99)) == []


class TestBritishSpellings:
    def test_a_british_form_in_prose_is_flagged(self) -> None:
        assert british_spellings("the colour of the behaviour here") == ["colour", "behaviour"]

    def test_a_british_form_inside_an_identifier_is_flagged(self) -> None:
        # The reason the roster exists at all: a word scan that stopped at
        # identifier boundaries would never reach `CancelledError`.
        assert british_spellings("with suppress(asyncio.CancelledError):") == ["Cancelled"]

    def test_a_form_in_a_code_span_is_not_this_repo_prose_to_spell(self) -> None:
        assert british_spellings("pass `colour` to the vendor call") == []

    def test_a_form_in_a_url_is_not_this_repo_prose_to_spell(self) -> None:
        assert british_spellings("see https://example.com/api/colour for the shape") == []

    def test_the_roster_exempts_exactly_the_word_it_names(self) -> None:
        assert british_spellings("CancelledError and colour", exempt=["Cancelled"]) == ["colour"]

    def test_the_roster_excuses_a_word_only_in_the_file_that_needs_it(self) -> None:
        # A bare-word roster would excuse the everyday spelling repo-wide; ADR
        # 0041 names the site as well as the consumer, and so does this.
        assert roster_exemptions("tests/cli/conftest.py") == frozenset({"Cancelled"})
        assert roster_exemptions("docs/architecture.md") == frozenset()

    def test_a_format_with_no_extractor_yields_no_prose(self) -> None:
        # A lockfile and a generated contract are full of names another system
        # chose; the walk reaches them, and the standard does not govern them.
        assert spellable_lines("uv.lock", 'name = "colour-parser"') == []
        assert spellable_lines("notes.md", "the colour of it") == ["the colour of it"]

    def test_python_prose_reaches_the_standard_and_python_data_does_not(self) -> None:
        # The `.py` branch, asserted at the call site rather than through the
        # bare-string helper: dropping it would leave every Python file in the
        # repo unscanned with nothing to say so.
        assert spellable_lines("x.py", "X = 1  # the colour of it") == ["X = 1  # the colour of it"]
        assert british_spellings(spellable_lines("x.py", 'X = "the colour of it"')[0]) == []

    def test_a_literal_holding_a_wide_character_blanks_only_itself(self) -> None:
        # `ast` reports byte offsets. Slicing the decoded line with them shifts
        # the blank window one place per non-ASCII character to the left of the
        # literal, and both directions corrupt the scan: over-blanking eats the
        # comment the rule was meant to read, under-blanking leaves a fragment
        # of the literal whose only escape would be a roster entry.
        eaten = spellable_lines("x.py", 'X = "an em — dash"  # the colour of it')[0]
        assert eaten.endswith("# the colour of it")
        assert "dash" not in eaten
        assert british_spellings(eaten) == ["colour"]

        exposed = spellable_lines("x.py", 'f("————", "colour")')[0]
        assert british_spellings(exposed) == []
        # The shifted window used to leave a quote mark the line never had, and
        # truncate the punctuation that really was there.
        assert '"' not in exposed
        assert exposed.endswith(")")

    def test_a_skill_description_is_prose_the_standard_spells(self) -> None:
        # Frontmatter is the one place the two markdown rules part company: a
        # `description:` is read by a person, so it is spelled, but it is one
        # YAML line, so it is never wrapped. Asserted through `spellable_lines`,
        # because the decision lives at that call site and a private answer
        # there is how the wrap rule once came to skip what the spelling rule
        # read.
        assert british_spellings("description: the colour of it") == ["colour"]
        assert markdown_continuations("---\ndescription: a\nname: b\n---\n") == []
        assert "description: the colour of it" in spellable_lines(
            "s.md", "---\nname: x\ndescription: the colour of it\n---\n\nBody.\n"
        )


class TestMarkdownBody:
    def test_frontmatter_is_dropped_only_when_the_caller_asks(self) -> None:
        document = "---\nname: x\n---\n\nBody.\n"
        assert "name: x" not in _markdown_body(document, keep_frontmatter=False)
        assert "name: x" in _markdown_body(document, keep_frontmatter=True)

    def test_a_leading_thematic_break_is_not_frontmatter(self) -> None:
        # Only a mapping key on the line below makes the opener frontmatter.
        # Without that test the closing search runs to the next `---` anywhere
        # in the document and blanks every paragraph in between.
        document = "---\n\nA paragraph that was hard\nwrapped here.\n\n---\n\nMore.\n"
        assert "A paragraph that was hard" in _markdown_body(document, keep_frontmatter=False)
        assert markdown_continuations(document) == [4]

    def test_a_tilde_line_does_not_close_a_backtick_fence(self) -> None:
        assert "x = 1" not in _markdown_body("```\nx = 1\n~~~\n", keep_frontmatter=True)

    def test_an_unclosed_fence_is_reported_rather_than_blanking_the_tail(self) -> None:
        assert unclosed_fence("Prose.\n\n```\nx = 1\n") == 3
        assert unclosed_fence("Prose.\n\n```\nx = 1\n```\n") is None

    def test_the_american_form_is_clean(self) -> None:
        assert british_spellings("the color of the behavior here") == []


def test_the_walk_reaches_every_root_the_linter_covers() -> None:
    walked = {_repo_name(path) for path in _walked_sources()}
    # The two roots an enumerated `src`-and-`tests` pair left out. A comment
    # left short-wrapped in either used to pass every check in the repo.
    assert "scripts/export_openapi.py" in walked
    assert "migrations/env.py" in walked
    assert {"src", "tests"} < {name.split("/")[0] for name in walked}
    # `W505` excuses a shipped migration's body, so this rule excuses it too.
    # Disagreeing would fail a file the linter passes, with no edit that fixes
    # both.
    assert not any(name.startswith("migrations/versions/") for name in walked)


def test_the_wrap_width_is_anchored_to_the_linter_setting() -> None:
    # Reds when `max-doc-length` moves, which is the point. `W505` and this
    # module check the same paragraphs from opposite sides, so a width that
    # drifted out of step would leave a band of lines neither check reaches.
    # Re-anchor both numbers together rather than editing this one alone.
    assert _max_doc_length() == 80
    assert WRAP == 79


def test_the_prose_path_set_reaches_every_governed_root() -> None:
    covered = {_repo_name(path) for path in _prose_documents()}
    # ADR 0040 names five roots. Walking `*.md` reaches them only while each one
    # still holds a tracked document, so the rule's reach is asserted rather
    # than assumed — a moved README would otherwise drop out unnoticed.
    assert "README.md" in covered
    assert "CLAUDE.md" in covered
    assert "DOMAIN.md" in covered
    assert any(name.startswith("docs/") for name in covered)
    assert any(name.startswith(".claude/skills/") for name in covered)


def test_no_markdown_block_spans_more_than_one_line() -> None:
    documents = [(path, text) for path in _prose_documents() if (text := _file_text(path)) is not None]
    # Counting documents cannot tell a clean tree from a blanked one: a fence
    # left open blanks every line below it, and a blanked line reads exactly
    # like a blank one. The floor goes on the prose the rule actually reads.
    read = sum(
        1 for _, text in documents for line in _markdown_body(text, keep_frontmatter=False).splitlines() if line.strip()
    )
    assert len(documents) > 40, f"markdown-document walk returned only {len(documents)} documents"
    assert read > 800, f"markdown-body extraction returned only {read} prose lines across {len(documents)} documents"

    unterminated = [f"{_repo_name(path)}:{at}" for path, text in documents if (at := unclosed_fence(text)) is not None]
    assert not unterminated, (
        "fenced code block opened and never closed; every line below it is exempt from both markdown "
        "rules while it stays open:\n" + "\n".join(unterminated)
    )

    offenders = [f"{_repo_name(path)}:{number}" for path, text in documents for number in markdown_continuations(text)]
    assert not offenders, (
        "markdown blocks are hard wrapped; a paragraph, bullet, or blockquote is one line (ADR 0040):\n"
        + "\n".join(offenders)
    )


def test_no_glossary_definition_runs_past_the_ceiling() -> None:
    # Reds on a definition cell grown past the ceiling, which is the shape spec
    # creep takes here: a query contract, an error table, or a list of ADR
    # citations arriving one clause at a time inside what is meant to be a
    # definition.
    text = _file_text(_REPO / "DOMAIN.md")
    assert text is not None, "DOMAIN.md is unreadable, so the ceiling has nothing to hold"
    entries = glossary_definitions(text)
    # A pattern that stopped matching reports the same green as a glossary under
    # the ceiling, so the floor goes on what the rule was handed rather than on
    # the offender list. The word floor is the second half of that: a match that
    # kept the rows and lost the definition cell would clear a row count alone.
    words = sum(len(definition.split()) for _, _, definition in entries)
    assert len(entries) > 40, f"the glossary walk returned only {len(entries)} term rows"
    assert words > 1500, f"the glossary walk returned only {words} definition words across {len(entries)} rows"

    offenders = [f"DOMAIN.md:{number}: {term}, {count} words" for number, term, count in definitions_over_ceiling(text)]
    assert not offenders, _CEILING_FAILURE + "\n".join(offenders)


def test_prose_spells_american() -> None:
    documents = [(_repo_name(path), text) for path in _tracked("*") if (text := _file_text(path)) is not None]
    # A walk that quietly returned nothing would report the same green as a
    # clean repo, and the difference is the whole value of the check. The file
    # count cannot say that, because extraction happens two calls later: the
    # floor that matters is on the lines the standard was handed.
    scanned = [(name, line) for name, text in documents for line in spellable_lines(name, text)]
    assert len(documents) > 200, f"readable-file walk returned only {len(documents)} files"
    assert len(scanned) > 15000, f"prose extraction returned only {len(scanned)} lines from {len(documents)} files"
    # Per-format floors, because one extractor going quiet is the realistic
    # break and a total floor sleeps through it.
    from_python = sum(1 for name, _ in scanned if name.endswith(".py"))
    from_markdown = sum(1 for name, _ in scanned if name.endswith(".md"))
    assert from_python > 10000, f"the Python extractor returned only {from_python} lines"
    assert from_markdown > 1500, f"the markdown extractor returned only {from_markdown} lines"

    offenders = [
        f"{name}:{number}: {word}"
        for name, text in documents
        for exempt in [roster_exemptions(name)]
        for number, line in enumerate(spellable_lines(name, text), start=1)
        for word in british_spellings(line, exempt=exempt)
    ]
    assert not offenders, _SPELLING_FAILURE + "\n".join(offenders)


def test_the_roster_names_no_word_its_file_has_stopped_using() -> None:
    # Pinning the roster's contents does not pin that its consumer still exists.
    # A dead entry keeps excusing the everyday spelling in that file, which is
    # the "word someone did not want to change" ADR 0041 exists to catch.
    for (name, word), consumer in DELIBERATE_BRITISH.items():
        text = _file_text(_REPO / name)
        assert text is not None, f"DELIBERATE_BRITISH names {name}, which is unreadable"
        assert any(word in line for line in spellable_lines(name, text)), (
            f"DELIBERATE_BRITISH excuses {word!r} in {name} for {consumer}, and the word is no longer there"
        )


def test_no_prose_paragraph_strands_a_line() -> None:
    paragraphs = _prose_paragraphs()
    # Asserting on an empty offender list cannot tell "nothing is stranded" from
    # "the walk found no prose", and this repo has had that failure twice. Each
    # extractor carries its own floor, since either one going quiet leaves the
    # other's count high enough on its own to pass a total.
    sources = [text for path in _walked_sources() if (text := _file_text(path)) is not None]
    from_comments = sum(len(comment_paragraphs(text)) for text in sources)
    from_docstrings = sum(len(docstring_paragraphs(text)) for text in sources)
    assert len(paragraphs) > 400, f"prose-paragraph walk returned only {len(paragraphs)} paragraphs"
    assert from_comments > 250, f"the comment extractor returned only {from_comments} paragraphs"
    assert from_docstrings > 120, f"the docstring extractor returned only {from_docstrings} paragraphs"

    offenders = [
        f"{_repo_name(path)}:{at + index}: {paragraph[index].strip()}"
        for path, at, paragraph in paragraphs
        if (index := stranded_line(paragraph)) is not None
    ]
    assert not offenders, "prose lines stopped short mid-paragraph; rewrap the block, not the line:\n" + "\n".join(
        offenders
    )
