"""The prose rules the linter cannot state, over code and documents alike.

`W505` fails a doc line that runs past `max-doc-length`. Nothing fails one left
too *short* — and that is the shape an in-place edit leaves behind, because
substituting a word inside a wrapped paragraph pushes the overflow onto its own
line instead of reflowing the block. The formatter never reflows prose, so the
result survives format, lint, type check, and the whole suite.

Four guards answer that, and two of them read markdown rather than Python. A
document soft-wraps instead, one line per paragraph (ADR 0040), so a later diff
shows the sentence that changed rather than the reflow around it. A word scan
holds code and documents alike to the American spelling (ADR 0041).

The stranded rule is exact rather than a guess about raggedness: a line is
stranded when it stopped short of the wrap width while the next line still held
a word that would have fit. A paragraph's last line is exempt — that is where
prose ends, not where it was abandoned. Comments and docstrings differ only in
how prose is found, so what counts as stranded is asked in one place.

The guards share one strip of what the rules do not govern. Frontmatter, a
fenced block, a code span, a URL, and a Python literal that is not a docstring
all hold names another system chose, so they come out before any rule reads the
line, and both markdown rules read one definition of that region rather than
each keeping its own.

Neither the width nor the walked roots are written here. Both are read from the
linter's own settings, so a rule cannot drift out of step with the check it
pairs with and leave a band of lines that neither one reaches.

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
    return tomllib.loads((_REPO / "pyproject.toml").read_text())["tool"]["ruff"]


def _max_doc_length() -> int:
    """The linter's own prose width, read rather than copied.

    `W505` fails a doc line past this; the rules here fail one left short of it.
    A width duplicated in both places drifts the day one of them moves, and the
    drift is invisible — every line in the gap passes both checks.
    """
    return _ruff_config()["lint"]["pycodestyle"]["max-doc-length"]


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


def _text(line: str) -> str:
    """The prose on a line, with whatever marks it as prose removed — the `#` of
    a comment, the quotes opening or closing a docstring."""
    return line.strip().removeprefix("#").strip('"').strip()


def stranded_line(paragraph: list[str]) -> int | None:
    """Index of the first line that stopped short while the next line still had
    a word that would have fit, or None when the paragraph is well wrapped.

    `paragraph` is the raw source lines, prefix and indent included — the width
    being judged is the one a reader sees, which is why a docstring's opening
    quotes count toward its first line.
    """
    for index, (line, following) in enumerate(zip(paragraph, paragraph[1:], strict=False)):
        words = _text(following).split()
        if not words:
            continue
        if len(line) < STRANDED and len(line) + 1 + len(words[0]) <= WRAP:
            return index
    return None


def _paragraphs(lines: list[str]) -> list[list[str]]:
    """Runs of prose split on the blank line between one thought and the next.

    A line holding only quotes reads as blank: it closes a docstring rather than
    continuing its last sentence. Single-line runs drop out — a lone line has no
    following line to have stranded it.
    """
    found: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if _text(line):
            current.append(line)
        elif current:
            found.append(current)
            current = []
    if current:
        found.append(current)
    return [p for p in found if len(p) > 1]


def _is_prose(paragraph: list[str]) -> bool:
    # Structure is judged on the text, not the raw line — a `#` or a `"""` sits
    # where a list marker's own anchor would otherwise match. Unbreakables are
    # judged on the raw line, since a URL can appear anywhere in it.
    return not any(_STRUCTURED.search(_text(line)) or _UNBREAKABLE.search(line) for line in paragraph)


def comment_paragraphs(source: str) -> list[list[str]]:
    """Prose paragraphs of every run of standalone comment lines at one indent.

    Trailing comments are excluded: they sit at whatever column their code
    leaves them and are not wrapped prose.
    """
    paragraphs: list[list[str]] = []
    lines = source.splitlines()
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("#"):
            index += 1
            continue
        indent = len(lines[index]) - len(lines[index].lstrip())
        block: list[str] = []
        while (
            index < len(lines)
            and lines[index].lstrip().startswith("#")
            and len(lines[index]) - len(lines[index].lstrip()) == indent
        ):
            block.append(lines[index])
            index += 1
        paragraphs.extend(p for p in _paragraphs(block) if _is_prose(p))
    return paragraphs


def docstring_paragraphs(source: str) -> list[list[str]]:
    """Prose paragraphs of every module, class, and function docstring.

    Read off the source lines rather than the parsed string value, because the
    indent and the opening quotes are part of the width a reader sees. Only the
    docstring position counts — a triple-quoted string used as a value is data,
    and wrapping it would change it.
    """
    lines = source.splitlines()
    paragraphs: list[list[str]] = []
    for node in _docstring_constants(_parsed_module(source)):
        if not isinstance(node.value, str) or node.end_lineno is None:
            continue
        paragraphs.extend(p for p in _paragraphs(lines[node.lineno - 1 : node.end_lineno]) if _is_prose(p))
    return paragraphs


@cache
def _parsed_module(source: str) -> ast.Module:
    """One parse per distinct source. Three guards read the same files, and the
    tree is only ever read, so parsing it again per guard buys nothing."""
    return ast.parse(source)


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
# breaks are the code's own — joining them would change what they run.
_FENCE = re.compile(r"^\s*(?:```|~~~)")

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


def markdown_body(document: str, *, keep_frontmatter: bool) -> str:
    """`document` with its fenced code blanked out, line numbers kept.

    One definition of the region the markdown rules govern. What runs inside a
    fence belongs to another system, so no rule here reads it.

    The two rules part company on frontmatter, which is why the caller says.
    A `description:` is prose a person reads, so the standard spells it; it is
    also one YAML line that cannot be reflowed, so the wrap rule leaves it
    alone. That difference is a decision, and stating it at each call site is
    what keeps it from drifting back into two private answers.
    """
    lines = document.splitlines()
    opening = 0
    if not keep_frontmatter and lines and lines[0].strip() == "---":
        closing = next((n for n in range(1, len(lines)) if lines[n].strip() == "---"), None)
        if closing is not None:
            opening = closing + 1

    body = ["" for _ in range(opening)]
    fenced = False
    for line in lines[opening:]:
        if _FENCE.match(line):
            fenced = not fenced
            body.append("")
        else:
            body.append("" if fenced else line)
    return "\n".join(body)


def markdown_continuations(document: str) -> list[int]:
    """Line numbers of every line that continues the block above it — the hard
    wrap ADR 0040 rules out.

    A block is a paragraph, a bullet, or a blockquote line, and it ends where
    its own line does.
    """
    found: list[int] = []
    continuable = False
    for number, line in enumerate(markdown_body(document, keep_frontmatter=False).splitlines(), start=1):
        if not line.strip():
            continuable = False
            continue
        if continuable and not _BLOCK_START.match(line):
            found.append(number)
        continuable = not _UNCONTINUABLE.match(line)
    return found


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


def roster_exemptions(name: str) -> frozenset[str]:
    """The words the roster excuses in this file, and in no other."""
    return frozenset(word for glob, word in DELIBERATE_BRITISH if fnmatch(name, glob))


# A name another system chose. Neither is this repo's prose to spell, so both
# come out before the lookup rather than being excused after it.
_CODE_SPAN = re.compile(r"`[^`]*`")
_URL = re.compile(r"https?://\S*")

# Words as a reader reads them, identifiers included: `CancelledError` is two.
# A scan stopping at identifier boundaries never reaches the form inside one.
_WORD = re.compile(r"[A-Za-z][a-z]*")


def british_spellings(text: str, *, exempt: Collection[str] = ()) -> list[str]:
    """Every British form in `text`, as written, in the order it appears."""
    flagged = BRITISH_WORDS - {word.lower() for word in exempt}
    stripped = _URL.sub(" ", _CODE_SPAN.sub(" ", text))
    return [word for word in _WORD.findall(stripped) if word.lower() in flagged]


def _without_literals(source: str) -> str:
    """`source` with every string constant that is not a docstring blanked out.

    This repo's prose in Python is its comments and its docstrings. A bare
    literal is data — a word list, a test fixture, an upstream state value —
    and gets the carve-out a code span gets in markdown. An identifier is not
    stripped, which is why `CancelledError` still needs its roster entry.

    Line numbers survive, so an offender still reports where it is.
    """
    lines = source.splitlines()
    tree = _parsed_module(source)
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
            stop = end_column if number == end_line - 1 else len(lines[number])
            lines[number] = lines[number][:start] + " " * (stop - start) + lines[number][stop:]
    return "\n".join(lines)


def spellable_lines(name: str, text: str) -> list[str]:
    """The lines of `text` the spelling standard governs, by file format.

    A format with no extractor here yields nothing rather than everything. The
    walk covers every tracked file, and a lockfile, a generated contract, and a
    captured scan fixture are all full of names another system chose; reading
    them as prose would leave a roster entry as the only way to quiet one.
    """
    if name.endswith(".py"):
        return _without_literals(text).splitlines()
    if name.endswith(".md"):
        return markdown_body(text, keep_frontmatter=True).splitlines()
    return []


def _text_of(path: Path) -> str | None:
    """The file as text, or None where it holds bytes rather than prose."""
    try:
        return path.read_text()
    except UnicodeDecodeError, OSError:
        return None


@cache
def _tracked(pattern: str) -> tuple[Path, ...]:
    """Paths git tracks, so an ignored working directory — a local review
    report, a virtualenv, a build tree — never counts as this repo's prose."""
    listed = subprocess.run(["git", "-C", str(_REPO), "ls-files", pattern], capture_output=True, text=True, check=True)
    return tuple(_REPO / name for name in listed.stdout.splitlines())


def _w505_exemptions() -> list[str]:
    """The globs the linter excuses from `W505`, so these rules excuse them too.

    A rule that failed a file the linter passes would have no edit that
    satisfies both.
    """
    ignores = _ruff_config()["lint"]["per-file-ignores"]
    return [glob for glob, codes in ignores.items() if "W505" in codes]


def _walked_sources() -> list[Path]:
    """Every tracked Python file `W505` reaches.

    The linter runs from the repo root, so the roots follow from what git
    tracks rather than from a list kept here — an enumerated pair went stale
    the moment a fourth tree grew, and the export script and the migration
    environment module sat outside it unchecked.
    """
    exempt = _w505_exemptions()
    return sorted(path for path in _tracked("*.py") if not any(fnmatch(_repo_name(path), glob) for glob in exempt))


def _prose_documents() -> list[Path]:
    """Every markdown document ADR 0040 governs.

    The set is every tracked `.md` rather than an enumerated list of roots: a
    document added under a new directory is prose the day it lands, and a list
    would silently stop covering it.
    """
    return sorted(_tracked("*.md"))


def _prose_paragraphs() -> list[tuple[Path, list[str]]]:
    return [
        (path, paragraph)
        for path in _walked_sources()
        for source in [path.read_text()]
        for paragraph in comment_paragraphs(source) + docstring_paragraphs(source)
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
        paragraph = docstring_paragraphs(source)[0]
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

    def test_consecutive_blockquote_lines_each_start_their_own_block(self) -> None:
        # The ask-block shape: every line carries its own `>`, so each is one
        # quoted line rather than one quote wrapped across several.
        assert markdown_continuations("> first line\n> second line\n") == []

    def test_a_lazily_continued_blockquote_is_reported(self) -> None:
        assert markdown_continuations("> a quote that was hard\nwrapped here.\n") == [2]

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

    def test_a_skill_description_is_prose_the_standard_spells(self) -> None:
        # Frontmatter is the one place the two markdown rules part company: a
        # `description:` is read by a person, so it is spelled, but it is one
        # YAML line, so it is never wrapped.
        assert british_spellings("description: the colour of it") == ["colour"]
        assert markdown_continuations("---\ndescription: a\nname: b\n---\n") == []

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
    documents = _prose_documents()
    assert len(documents) > 40, f"only {len(documents)} documents found — the walk is broken"

    offenders = [
        f"{_repo_name(path)}:{number}" for path in documents for number in markdown_continuations(path.read_text())
    ]
    assert not offenders, (
        "markdown blocks are hard wrapped; a paragraph, bullet, or blockquote is one line (ADR 0040):\n"
        + "\n".join(offenders)
    )


def test_prose_spells_american() -> None:
    documents = [(_repo_name(path), text) for path in _tracked("*") if (text := _text_of(path)) is not None]
    # A walk that quietly returned nothing would report the same green as a
    # clean repo, and the difference is the whole value of the check.
    assert len(documents) > 200, f"only {len(documents)} readable files found — the walk is broken"

    offenders = [
        f"{name}:{number}: {word}"
        for name, text in documents
        for exempt in [roster_exemptions(name)]
        for number, line in enumerate(spellable_lines(name, text), start=1)
        for word in british_spellings(line, exempt=exempt)
    ]
    assert not offenders, (
        "British spellings in prose this repo owns; write the American form, or, for a form another "
        "system matches by string, add it to DELIBERATE_BRITISH with the consumer that requires "
        "it (ADR 0041):\n" + "\n".join(offenders)
    )


def test_no_prose_paragraph_strands_a_line() -> None:
    paragraphs = _prose_paragraphs()
    # Asserting on an empty offender list cannot tell "nothing is stranded" from
    # "the walk found no prose", and this repo has had that failure twice.
    assert len(paragraphs) > 150, f"only {len(paragraphs)} prose paragraphs found — the walk is broken"

    offenders = [
        f"{_repo_name(path)}: {paragraph[index].strip()}"
        for path, paragraph in paragraphs
        if (index := stranded_line(paragraph)) is not None
    ]
    assert not offenders, "prose lines stopped short mid-paragraph; rewrap the block, not the line:\n" + "\n".join(
        offenders
    )
