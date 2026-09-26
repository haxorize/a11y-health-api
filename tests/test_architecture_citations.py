"""Every `docs/architecture.md` section a tracked file cites, by quoted
heading or by `#fragment` link, names a heading the document has. Code
headers, ADRs, and skills point into the document by heading, and renaming a
heading without its citers leaves each pointer aimed at nothing, with no link
checker to notice.
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
_FRAGMENT = re.compile(r"architecture\.md#([\w-]+)")
_HEADING = re.compile(r"^#+\s+(?:\d+\.\s+)?(.+?)\s*$")
_RAW_HEADING = re.compile(r"^#+\s+(.+?)\s*$")


def _citations(text: str) -> list[str]:
    return [_LINE_BREAK.sub(" ", cited) for cited in _CITATION.findall(text)]


def _heading_lines(document: str) -> list[str]:
    lines: list[str] = []
    fenced = False
    for line in document.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and line.startswith("#"):
            lines.append(line)
    return lines


def _headings(document: str) -> set[str]:
    return {heading.group(1) for line in _heading_lines(document) if (heading := _HEADING.match(line))}


def _anchor(heading: str) -> str:
    # GitHub's slug: lowercase, punctuation dropped, each space a hyphen. The
    # section number stays in, so `3-the-scan-run-lifecycle`.
    return re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")


def _anchors(document: str) -> set[str]:
    return {_anchor(heading.group(1)) for line in _heading_lines(document) if (heading := _RAW_HEADING.match(line))}


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

    def test_a_fragment_link_is_read(self) -> None:
        text = "[the lifecycle](architecture.md#3-the-scan-run-lifecycle)'s to state."

        assert _FRAGMENT.findall(text) == ["3-the-scan-run-lifecycle"]

    def test_a_numbered_heading_anchors_with_its_number(self) -> None:
        document = "## 2. The scoring & rollup model\n\n### How errors become HTTP status codes\n"

        assert _anchors(document) == {"2-the-scoring--rollup-model", "how-errors-become-http-status-codes"}

    def test_a_numbered_heading_is_cited_without_its_number(self) -> None:
        document = "# Architecture\n\n## 2. The scoring & rollup model\n\n```bash\n# not a heading\n```\n"

        assert _headings(document) == {"Architecture", "The scoring & rollup model"}


def test_every_cited_heading_exists() -> None:
    document = _file_text(_REPO / _ARCHITECTURE)
    assert document is not None, f"{_ARCHITECTURE} is unreadable"
    headings = _headings(document)
    anchors = _anchors(document)

    citing = {}
    linking = {}
    # This file's cases quote citations as data, escaped line breaks included.
    for path in set(_tracked("*")) - {_REPO / "tests" / "test_architecture_citations.py"}:
        text = _file_text(path)
        if text is not None and (cited := _citations(text)):
            citing[str(path.relative_to(_REPO))] = cited
        if text is not None and (linked := _FRAGMENT.findall(text)):
            linking[str(path.relative_to(_REPO))] = linked
    # A floor, not a count to keep in step: it proves the walk read the tree,
    # which an empty `dangling` below cannot.
    assert len(citing) >= 20, f"only {len(citing)} files cite {_ARCHITECTURE} — the walk is not reading the tree"

    assert linking, f"no file links into {_ARCHITECTURE} by fragment — the fragment walk is not reading the tree"

    dangling = {path: sorted(set(cited) - headings) for path, cited in citing.items() if set(cited) - headings}
    dangling |= {path: sorted(set(linked) - anchors) for path, linked in linking.items() if set(linked) - anchors}
    assert dangling == {}, f"citations naming no heading in {_ARCHITECTURE}: {dangling}"
