---
name: code-documentation
description: This repo's prose regime — where comprehension lives (prose and `docs/architecture.md`, not blanket docstrings), when a docstring is written, and the 80-column and bare-`#` rules the guards check. Use when writing or editing a docstring, a comment block, a module header, or `docs/architecture.md`, when `W505` or `test_prose_shape.py` fails, or when reviewing a diff for restated types.
---

# Code documentation

Comprehension lives in prose, not blanket docstrings — the why is [ADR 0018](../../../docs/adr/0018-documentation-strategy-prose-over-docstrings.md). Four guards check the shape, so a failure from any of them is a rule below, not a style preference.

## Where a thing is explained

- **Cross-cutting behavior and architecture go in [`docs/architecture.md`](../../../docs/architecture.md)** — the layer model, scoring and rollup, scan-run lifecycle, pagination, the contract pipeline, operating. `DOMAIN.md` holds the domain model — terms, relationships, and the mechanisms named in domain language — not the layer model or operating notes.
- **Module docstrings only on modules whose job isn't self-evident** (scoring, pagination, the axe boundary), and they point to the relevant `architecture.md` section rather than re-explaining it. No docstring on a module whose purpose is clear from its path.
- **Function docstrings only for a caller contract the signature can't express** — a precondition or a `Raises:` (see `paginate()`).
- **Explain the non-obvious; never restate what types and names already say.** No `Args:`/`Returns:` blocks — the type hints carry that. Docstrings, when written, are plain prose.

## Shape the guards check

- **Prose *in code* wraps at 80 columns** — a docstring or a comment, narrower than the 120 the formatter allows code, because a paragraph running the full code width is one nobody re-reads. `ruff`'s `W505` checks it (`lint.pycodestyle.max-doc-length`); shipped migration revisions are exempt, being history the suite runs rather than code to edit. This does **not** reach a markdown document: those soft-wrap, one line per paragraph, under [ADR 0040](../../../docs/adr/0040-prose-documents-soft-wrap-one-line-per-paragraph.md) — hard-wrapping one reds the guard below.
- **Separate comment paragraphs with a bare `#`.** It is what tells a reader — and `tests/test_prose_shape.py` — that a short line ends a thought rather than trailing off.

The two checks split the mechanical part: `W505` fails a doc line that is too _long_, and `tests/test_prose_shape.py` fails one left too _short_ — a line that stopped before the wrap width while the next line still held a word that would have fit, in comments and docstrings alike. That second shape is what an in-place edit leaves behind, since the formatter never reflows prose. **When you change a word inside a comment or docstring, rewrap the whole block, not the line.** Structured blocks are skipped by both — list items, `Raises:`, examples, a line holding a URL or pragma (`_STRUCTURED` and `_UNBREAKABLE` in the test) — because their line breaks are the author's, not the wrap's. No ruff `D` rules enforce the rest; shape and content are judgment, applied here.

The other two guards live in the same module and ask for a different fix, so read which one failed before rewrapping anything:

- **A markdown continuation** ([ADR 0040](../../../docs/adr/0040-prose-documents-soft-wrap-one-line-per-paragraph.md)) — a paragraph, bullet, or blockquote in a `.md` file split across lines. The fix is to **join it onto one line**, not to rewrap it. A quoted line ends where the author put a hard break (two trailing spaces); without one, a following `>` line reads as a wrapped quote.
- **A British spelling** ([ADR 0041](../../../docs/adr/0041-prose-spells-american-with-three-carve-outs.md)) — over code prose and markdown alike. The fix is to **change the word**. Only where another system matches the form by string does it take a `DELIBERATE_BRITISH` entry, keyed by the file whose consumer requires it.
