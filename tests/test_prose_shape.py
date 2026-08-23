"""The half of prose shape `W505` cannot see, for comments and docstrings both.

`W505` fails a doc line that runs past 80. Nothing fails one left too *short* —
and that is the shape an in-place edit leaves behind, because substituting a
word inside a wrapped paragraph pushes the overflow onto its own line instead of
reflowing the block. The formatter never reflows prose, so the result survives
format, lint, type check, and the whole suite.

The rule here is exact rather than a guess about raggedness: a line is stranded
when it stopped short of the wrap width while the next line still held a word
that would have fit. A paragraph's last line is exempt — that is where prose
ends, not where it was abandoned.

One rule, two sources. What differs is only how prose is found: a comment's
paragraph is a run of `#` lines, a docstring's is a run of lines inside the
quotes. What counts as stranded is the same question in both, so it is asked in
one place.

See `.claude/skills/code-documentation/SKILL.md` ("Shape the guards check")
for the width this pairs with and the rewrap rule a failure here asks for.
"""

import ast
import re
from pathlib import Path

import a11y_health

# The width prose wraps to. One under `max-doc-length`, so a line filled to the
# limit still reads as full rather than as one word short of the check.
WRAP = 79

# Below this a line is short enough that stopping there needs a reason. The
# repo's blocks sit in a flat region either side of it: every value from 40 to
# 65 flags the same single block, so nothing here balances on the exact number.
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
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)):
            continue
        if not isinstance(first.value.value, str) or first.end_lineno is None:
            continue
        paragraphs.extend(p for p in _paragraphs(lines[first.lineno - 1 : first.end_lineno]) if _is_prose(p))
    return paragraphs


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


def _prose_paragraphs() -> list[tuple[Path, list[str]]]:
    roots = [Path(a11y_health.__file__).parent, Path(__file__).parent]
    return [
        (path, paragraph)
        for root in roots
        for path in sorted(root.rglob("*.py"))
        for source in [path.read_text()]
        for paragraph in comment_paragraphs(source) + docstring_paragraphs(source)
    ]


def test_no_prose_paragraph_strands_a_line() -> None:
    paragraphs = _prose_paragraphs()
    # Asserting on an empty offender list cannot tell "nothing is stranded" from
    # "the walk found no prose", and this repo has had that failure twice.
    assert len(paragraphs) > 150, f"only {len(paragraphs)} prose paragraphs found — the walk is broken"

    offenders = [
        f"{path}: {paragraph[index].strip()}"
        for path, paragraph in paragraphs
        if (index := stranded_line(paragraph)) is not None
    ]
    assert not offenders, "prose lines stopped short mid-paragraph; rewrap the block, not the line:\n" + "\n".join(
        offenders
    )
