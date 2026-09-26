"""Every quoted `docs/architecture.md` section a tracked file cites names a
heading the document has. Code headers, ADRs, and skills point into the
document by heading text, and renaming a heading without its citers leaves
each pointer aimed at nothing, with no link checker to notice.
"""

import re

import pytest

from tests.test_prose_shape import _REPO, _file_text, _tracked

_ARCHITECTURE = "docs/architecture.md"
# The file name, then a comma, whitespace, or opening parenthesis, then the
# quoted heading; a quote straight after the name closes a string literal
# instead. A citation wrapped across lines carries the next line's indent and,
# in code, its comment marker, both of which `_LINE_BREAK` folds.
_CITATION = re.compile(r'architecture\.md`?(?=[,\s(]),?(?:\s*#)?\s*\(?"([^"]+)"')
_LINE_BREAK = re.compile(r"\s*\n\s*(?:#\s*)?")
_HEADING = re.compile(r"^#+\s+(?:\d+\.\s+)?(.+?)\s*$")


def _citations(text: str) -> list[str]:
    return [_LINE_BREAK.sub(" ", cited) for cited in _CITATION.findall(text)]


def _headings(document: str) -> set[str]:
    headings: set[str] = set()
    fenced = False
    for line in document.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and (heading := _HEADING.match(line)):
            headings.add(heading.group(1))
    return headings


class TestCitationReading:
    @pytest.mark.parametrize(
        ("text", "cited"),
        [
            ('See `docs/architecture.md` ("Pagination").', ["Pagination"]),
            ('see architecture.md, "The layers".', ["The layers"]),
            ('See docs/architecture.md "The layers" for', ["The layers"]),
            ('See `docs/architecture.md` ("The scoring &\nrollup model").', ["The scoring & rollup model"]),
            (
                '# break UI codegen (docs/architecture.md, "The OpenAPI\n    # contract pipeline").',
                ["The OpenAPI contract pipeline"],
            ),
            ("[`docs/architecture.md`](architecture.md) owns the story.", []),
            ('roster("docs/architecture.md") == frozenset()\nassert text is not None, "unreadable"', []),
        ],
        ids=[
            "parenthesized",
            "comma",
            "bare",
            "wrapped-docstring",
            "wrapped-comment",
            "link-without-quote",
            "string-literal",
        ],
    )
    def test_citations_are_read_in_every_spelling(self, text: str, cited: list[str]) -> None:
        assert _citations(text) == cited

    def test_a_numbered_heading_is_cited_without_its_number(self) -> None:
        document = "# Architecture\n\n## 2. The scoring & rollup model\n\n```bash\n# not a heading\n```\n"

        assert _headings(document) == {"Architecture", "The scoring & rollup model"}


def test_every_cited_heading_exists() -> None:
    document = _file_text(_REPO / _ARCHITECTURE)
    assert document is not None, f"{_ARCHITECTURE} is unreadable"
    headings = _headings(document)

    citing = {}
    # This file's cases quote citations as data, escaped line breaks included.
    for path in set(_tracked("*")) - {_REPO / "tests" / "test_architecture_citations.py"}:
        text = _file_text(path)
        if text is not None and (cited := _citations(text)):
            citing[str(path.relative_to(_REPO))] = cited
    # A floor, not a count to keep in step: it proves the walk read the tree,
    # which an empty `dangling` below cannot.
    assert len(citing) >= 20, f"only {len(citing)} files cite {_ARCHITECTURE} — the walk is not reading the tree"

    dangling = {path: sorted(set(cited) - headings) for path, cited in citing.items() if set(cited) - headings}
    assert dangling == {}, f"citations naming no heading in {_ARCHITECTURE}: {dangling}"
