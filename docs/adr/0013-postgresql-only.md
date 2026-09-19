# PostgreSQL-only — no abstraction layer, no fallback dialect

The schema and queries depend on PostgreSQL features that are not portable to other RDBMS: `BIGINT GENERATED ALWAYS AS IDENTITY`, `JSONB` columns with GIN indexes, native `ENUM` types, and `LENGTH(...) <= N` CHECK constraints over unbounded `TEXT`. Tests run against a real Postgres database, not SQLite.

Considered and rejected:
- **Stay dialect-agnostic, target the SQLAlchemy core only**: would forbid JSONB (PageResult.raw_json, NodeFinding.checks, RuleFinding.classifications, RuleFinding.tags, RuleFinding.wcag_criteria), GIN indexes on those columns, and PG-native enums. Each of those choices was load-bearing on its own merits — see ADR-0008, ADR-0014. — amended: see Amendments 2026-09-19
- **SQLite for tests, Postgres for prod**: a common shortcut. Rejected because it would mask exactly the dialect-specific bugs we'd most want tests to catch (JSONB shape, enum values, IDENTITY behavior, FK ON DELETE semantics). The transactional-rollback test fixture (ADR-0011) also depends on real savepoint behavior.

The portability tax is real (a future "let's run on Aurora MySQL" request would be a multi-month rewrite), and we're paying it deliberately.

## Amendments

- **2026-09-19 (#152 review)** — **The JSONB list in the first rejected alternative omits `NodeFinding.target`**, a sixth JSONB column (`models/node_finding.py`). The same omission in [ADR 0008](0008-defer-jsonb-by-access-pattern.md) was corrected there by amendment on this date. Counting it changes nothing about the decision: it is one more column a dialect-agnostic core could not hold.
