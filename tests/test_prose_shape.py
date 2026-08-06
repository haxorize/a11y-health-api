"""The half of prose shape `W505` cannot see.

`W505` fails a doc line that runs past 80. Nothing fails one left too *short* —
and that is the shape an in-place edit leaves behind, because substituting a
word inside a wrapped paragraph pushes the overflow onto its own line instead of
reflowing the block. The formatter never reflows prose, so the result survives
format, lint, type check, and the whole suite.

The rule here is exact rather than a guess about raggedness: a line is stranded
when it stopped short of the wrap width while the next line still held a word
that would have fit. A paragraph's last line is exempt — that is where prose
ends, not where it was abandoned.

See CLAUDE.md ("Code documentation") for the width this pairs with.
"""

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

# Line breaks these own are structural — a list item, a doctest, a table row —
# so joining them onto the previous line would be wrong, not tidier.
_STRUCTURED = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s|>>>|:param|:return|Raises:|Args:|\|")

# A URL or pragma cannot be broken and cannot move, so a line ending short of
# one is the wrap doing its best. `W505` exempts these for the same reason.
_UNBREAKABLE = re.compile(r"https?://|noqa|ty:\s*ignore|type:\s*ignore")


def _text(line: str) -> str:
    return line.lstrip().removeprefix("#").strip()


def stranded_line(paragraph: list[str]) -> int | None:
    """Index of the first line that stopped short while the next line still had
    a word that would have fit, or None when the paragraph is well wrapped.

    `paragraph` is the raw source lines, comment prefix and indent included —
    the width being judged is the one a reader sees.
    """
    for index, (line, following) in enumerate(zip(paragraph, paragraph[1:], strict=False)):
        words = _text(following).split()
        if not words:
            continue
        if len(line) < STRANDED and len(line) + 1 + len(words[0]) <= WRAP:
            return index
    return None


def comment_paragraphs(source: str) -> list[list[str]]:
    """Every run of standalone comment lines at one indent, split on the bare
    `#` that separates one paragraph from the next.

    Trailing comments are excluded: they sit at whatever column their code
    leaves them and are not wrapped prose. Structural and unbreakable blocks
    drop out here rather than in the rule, which keeps the rule about width
    alone.
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
        # Structure is judged on the text, not the raw line — the `#` sits where
        # a list marker's own anchor would otherwise match. Unbreakables are
        # judged on the raw line, since a URL can appear anywhere in it.
        if any(_STRUCTURED.search(_text(line)) or _UNBREAKABLE.search(line) for line in block):
            continue
        current: list[str] = []
        for line in block:
            if _text(line):
                current.append(line)
            elif current:
                paragraphs.append(current)
                current = []
        if current:
            paragraphs.append(current)
    return [p for p in paragraphs if len(p) > 1]


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


class TestCommentParagraphs:
    def test_bare_hash_separates_paragraphs(self) -> None:
        source = "# first paragraph line one\n# ends here.\n#\n# second paragraph begins\n# and ends.\n"
        assert len(comment_paragraphs(source)) == 2

    def test_structural_and_unbreakable_blocks_are_excluded(self) -> None:
        assert comment_paragraphs("# - a list item\n# - another item\n") == []
        assert comment_paragraphs("# see\n# https://example.com/very/long/path\n") == []

    def test_trailing_comments_are_not_prose(self) -> None:
        assert comment_paragraphs("x = 1  # trailing\ny = 2  # also trailing\n") == []


def test_no_comment_paragraph_strands_a_line() -> None:
    roots = [Path(a11y_health.__file__).parent, Path(__file__).parent]
    paragraphs = [
        (path, paragraph)
        for root in roots
        for path in sorted(root.rglob("*.py"))
        for paragraph in comment_paragraphs(path.read_text())
    ]
    # Asserting on an empty offender list cannot tell "nothing is stranded" from
    # "the walk found no prose", and this repo has had that failure twice.
    assert len(paragraphs) > 50, f"only {len(paragraphs)} comment paragraphs found — the walk is broken"

    offenders = [
        f"{path}: {paragraph[index].strip()}"
        for path, paragraph in paragraphs
        if (index := stranded_line(paragraph)) is not None
    ]
    assert not offenders, "comment lines stopped short mid-paragraph; rewrap the block, not the line:\n" + "\n".join(
        offenders
    )
