# Code comprehension lives in prose docs, not blanket docstrings

The repo is handed to a team that is mostly *reading* the code (with occasional
Python edits) and whose comprehension gaps are, in priority order: domain
behavior, then architecture, then operations — not Python language fluency.
Docstrings and comments do not teach a language, so we do not blanket-document to
close a fluency gap that comments cannot close. Instead, comprehension is carried
by three artifacts with non-overlapping jobs:

- **`DOMAIN.md`** stays a glossary — vocabulary and relationships only, no
  algorithm narrative or spec.
- **One narrative doc** (`docs/architecture.md`) owns the cross-cutting
  *behavioral and structural* story: the layer model, the scoring/rollup
  lifecycle, the scan-run state machine, pagination, the OpenAPI contract
  pipeline, and an operating/debugging section. This is the primary artifact for
  a reader who does not want to parse Python.
- **Module docstrings**, only on modules whose purpose is not self-evident from
  path + a glance (`core/pagination.py`, `core/database.py`,
  `services/score_snapshot.py`, `services/scoring_orchestration.py`,
  `services/owner.py`, `schemas/axe_payload.py`, `schemas/_tag_parsing.py`),
  orient a reader who lands in the file and point to the relevant narrative-doc
  section rather than re-explaining it.

Docstrings, when written, are plain prose. Type hints are comprehensive, so an
`Args:`/`Returns:` block would only restate the signature; the one carve-out is a
single sentence for a parameter or `Raises:` whose meaning genuinely is not in
the signature (e.g. `paginate`'s NOT-NULL keyset requirement). Every artifact
explains the non-obvious; nothing restates what the code already says.

Considered and rejected:
- **Universal module docstrings (one on every file):** on the CRUD trio
  (app/brand/org_unit models, schemas, services) the only honest header is a
  restatement of the filename ("SQLAlchemy model for App"). Manufacturing that
  noise to satisfy a pattern fights the why-only house style; the reader's
  predictable entry point is the narrative doc + `DOMAIN.md`, not a header on
  every file.
- **Per-function docstrings throughout:** the dominant gap is domain behavior,
  which is *cross-cutting* (scoring spans functions and files) and belongs in
  prose, not scattered across function headers that rot fastest and duplicate the
  type signatures.
- **Behavioral narrative inside service module docstrings instead of a doc:**
  closer to the code, but harder for a non-Python reader to reach and more prone
  to drift; the narrative doc is the single home, module docstrings only point to
  it.
- **Google-style (`Args:`/`Returns:`/`Raises:`) docstrings:** the rigid template
  duplicates comprehensive type hints and drifts the moment a parameter changes.
- **Enforcing docstrings with ruff `D` (pydocstyle) rules:** the presence rules
  (`D100`, `D103`) mandate docstrings everywhere, which would force the exact
  universal noise rejected above. The strategy is judgment-based ("is this
  docstring earned?"), which a linter cannot encode — so the convention is
  recorded (here and in `CLAUDE.md`) rather than linted.
