---
name: database
description: Database conventions for this project (PostgreSQL schema design + SQLAlchemy ORM, plus query patterns). Use when creating or editing models, defining columns, choosing data types, writing migrations, adding indexes/constraints, or writing services and queries that hit the database.
---

# Database Conventions

## Data types

- **IDs**: `BIGINT GENERATED ALWAYS AS IDENTITY` for PKs; `UUID` only when opacity or federation is needed
- **Strings**: `TEXT` always; enforce length with `CHECK (LENGTH(col) <= n)`, never `VARCHAR(n)` or `CHAR(n)`. The model reads `n` from its named constant in `core/slug.py` (`NAME_MAX_LENGTH`, `SLUG_MAX_LENGTH`), the one the request schema's `max_length` reads too; the migration writes it as a literal, and `tests/migrations/test_check_constraints.py` holds every migrated check constraint equal to the model's
- **Timestamps**: `TIMESTAMPTZ` always, never `TIMESTAMP`; default `now()` for creation times. In SQLAlchemy ORM, use `DateTime(timezone=True)` — it maps to `TIMESTAMPTZ` in PostgreSQL
- **Booleans**: `BOOLEAN NOT NULL` unless tri-state is intentional
- **Scores and ratios**: `FLOAT`. Nothing here is financial, so `NUMERIC` has no site in this schema
- **JSON**: `JSONB`. Indexing and loading are separate calls. GIN goes on a column a query filters — `rule_finding.wcag_criteria` ([ADR 0014](../../../docs/adr/0014-wcag-criteria-as-jsonb-array.md)) and `rule_finding.classifications` ([ADR 0031](../../../docs/adr/0031-typed-classification-compact-wire-shape.md)) each carry one. Loading is [ADR 0008](../../../docs/adr/0008-defer-jsonb-by-access-pattern.md)'s call by access pattern: `deferred()` for a large column read only on a detail endpoint, which is why `page_result.raw_json` and `node_finding.checks` are deferred and unindexed. Served but not filtered is the third case and takes neither — `rule_finding.tags` and `node_finding.target`

### Do not use

`timestamp` (without tz), `char(n)`, `varchar(n)`, `money`, `timetz`, `serial`

## Model definition

Models in `src/a11y_health/models/` inherit from `core.database.Base`. `Base` provides `id` (BIGINT IDENTITY PK). Mutable tables also inherit `TimestampMixin` for `created_at`/`updated_at`.

Declare a constraint name as a module-level constant when something has to refer to it. A `ForeignKey` earns a `name=` when an `integrity.guard` call maps its violation to a domain error: the auto-generated `<table>_<col>_fkey` cannot be mapped, and changing a named constraint's `ON DELETE` later costs a rename migration first. [ADR 0028](../../../docs/adr/0028-integrity-guard-constraint-identity-savepoint.md) names the three a guard maps — `fk_org_unit_parent_id`, `fk_app_org_unit_id`, `fk_score_snapshot_org_unit_id`, all `RESTRICT` parents, mapped at `services/org_unit.py`. Five FKs carry names in all: the two brand parents are named without being mapped, which the rule neither asks for nor forbids. The six `CASCADE` owned-child FKs are unnamed on purpose, nothing mapping them; do not add names to them or to a new one. Index names stay bare literals on the same test, which is why the example's `Index(...)` is not a constant. `models/app.py` is the worked example:

```python
UQ_APP_SLUG = "uq_app_slug"
CK_APP_NAME_LENGTH = "ck_app_name_length"
FK_APP_ORG_UNIT_ID = "fk_app_org_unit_id"


class App(TimestampMixin, Base):
    __tablename__ = "app"
    __table_args__ = (
        CheckConstraint(f"LENGTH(name) <= {NAME_MAX_LENGTH}", name=CK_APP_NAME_LENGTH),
        UniqueConstraint("slug", name=UQ_APP_SLUG),
        Index("ix_app_org_unit_id", "org_unit_id"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    org_unit_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("org_unit.id", ondelete="RESTRICT", name=FK_APP_ORG_UNIT_ID), nullable=False
    )
```

For an enum column and a timestamp column, `models/scan_run.py` is the shape: `Enum(ScanRunStatus, name="scan_run_status", values_callable=enum_values)` and `DateTime(timezone=True)`.

Omit `TimestampMixin` on immutable child records that are always created and deleted with their parent (e.g., `rule_finding`, `node_finding`).

## Enums

All domain enums live in `models/enums.py`. Import from there — do not define enums alongside model classes. Add new enums to `models/enums.py` when needed.

In SQLAlchemy, always pass `values_callable=enum_values` (from `core.database`) so enum *values* (not names) are stored. When reusing an enum type already created by another model, add `create_type=False`:
```python
Enum(Impact, name="impact", create_type=False, values_callable=enum_values)
```

## Models package

Re-export all ORM model classes in `models/__init__.py` with `__all__`. This ensures Alembic autogenerate and the test conftest's `from a11y_health.models import *` discover all tables.

## Table conventions

- `NOT NULL` everywhere semantically required
- Singular table names matching the resource (`org_unit`, `scan_run`, `score_snapshot`)
- PK column named `id` (not `<resource>_id`)
- Use a plain tuple for `__table_args__` — no trailing `{}` dict:
  ```python
  __table_args__ = (
      UniqueConstraint("slug", name=UQ_APP_SLUG),
      Index("ix_app_org_unit_id", "org_unit_id"),
  )
  ```

## Constraints

- **PK**: every reference table gets one
- **FK**: always specify `ON DELETE` action; always leave the FK column indexed, since Postgres does not auto-index FKs — a dedicated single-column index unless a composite index, a partial index, or a UNIQUE constraint already leads with that column. Five of the eleven FK columns have none of their own for that reason, and two migrations dropped the redundant ones (`632bbe98aa6a`, `c31f27959a81`); do not put them back. Use `RESTRICT` for parent/reference relationships and `CASCADE` for owned children that should be deleted with their parent
- **UNIQUE**: a uniqueness rule that holds only for some rows is a partial unique `Index`, not a `UniqueConstraint` — see `UQ_SCORE_SNAPSHOT_ORG_UNIT_SNAPSHOT_AT` and its twin `UQ_SCORE_SNAPSHOT_BRAND_SNAPSHOT_AT`, whose predicates track `CK_SCORE_SNAPSHOT_OWNER`'s mutually exclusive owner columns, and `UQ_ORG_UNIT_SINGLE_ROOT`, whose predicate carries ADR 0026's at-most-one-parentless-org-unit rule. `NULLS NOT DISTINCT` has no site in this schema: the partial shape covers the nullable cases instead
- **CHECK**: combine with `NOT NULL` since NULLs pass checks
- **Naming**: name CHECK, UNIQUE and `Index` constraints explicitly, to the pattern (`ck_<table>_<col>_<desc>`, `uq_<table>_<col>`, `ix_<table>_<col>`, `fk_<table>_<col>`) — autogenerate's default for these is unreadable in a migration. FKs are the exception, named only where mapped (§ Model definition). Export the names a constraint→error mapping passes to `integrity.guard` as module-level constants (e.g., `UQ_APP_SLUG`, `FK_APP_ORG_UNIT_ID`); see the fastapi skill's Services section

## Indexes

Two access methods, B-tree and GIN, in four shapes: plain single-column, composite, partial, and GIN. Another access method (BRIN, hash) or a covering `postgresql_include` is an ADR, not a judgment call at the model; none has a site in this schema today.

- **Composite**: equality columns first, range columns last; prefer one composite over two singletons when queries `AND` the columns (`ix_rule_finding_page_result_id_type`, `ix_page_result_scan_run_id_id`)
- **Partial**, via `postgresql_where`, when the predicate is what makes the rule true. Three sites: the two `score_snapshot` rollup-owner indexes, which are the backstop deciding rollup write races ([ADR 0015](../../../docs/adr/0015-score-snapshot-append-only.md), [ADR 0029](../../../docs/adr/0029-per-owner-advisory-lock-rollup-serialization.md)), and `UQ_ORG_UNIT_SINGLE_ROOT`. A fourth owner type takes a fourth index, copied from both twins rather than from one:
  ```python
  from sqlalchemy import text

  Index(
      UQ_SCORE_SNAPSHOT_ORG_UNIT_SNAPSHOT_AT,
      "org_unit_id",
      "snapshot_at",
      unique=True,
      postgresql_where=text("org_unit_id IS NOT NULL"),
  )
  ```
- **GIN** on a JSONB column a query filters: `Index("ix_rule_finding_wcag_criteria", "wcag_criteria", postgresql_using="gin")`
- **Every index is built non-concurrently.** `migrations/env.py` wraps the whole `run_migrations()` call in one transaction — one `BEGIN` for the entire run, not one per revision, so a failure mid-`upgrade head` rolls back every revision in it — and `CREATE INDEX CONCURRENTLY` cannot run inside a transaction. A new index on `rule_finding` or `page_result` therefore holds a `SHARE` lock against Page Result creation for the whole build. Adding one to a large table needs `transaction_per_migration=True` in `env.py` *and* an autocommit block for that revision, not the autocommit block alone; the existing indexes were all applied when the tables were small

## Relationships

Do not use `relationship()`. Use explicit FK columns only. This avoids lazy-load pitfalls with async sessions.

## Deferred columns

Use `deferred()` for large columns (e.g., a JSONB document like Raw JSON) that should not be loaded in default queries:
```python
from sqlalchemy.orm import deferred

raw_json: Mapped[dict[str, Any]] = deferred(mapped_column(JSONB, nullable=False))
```

Omit deferred columns from list-level Read schemas — they are not loaded by default queries. Detail schemas that always `undefer()` the column in their query path may include it.

## Query patterns

- **No N+1**: since `relationship()` is banned, batch parent-then-children with `in_()` (compiles to `WHERE col = ANY(...)`):
  ```python
  apps = (await session.execute(select(App).where(App.id.in_(app_ids)))).scalars().all()
  ```
- **Batch inserts** at Page Result creation — never loop single-row INSERTs. `session.execute(insert(Model), list_of_dicts)` issues one statement per chunk
- **Cursor/keyset pagination** for list endpoints, never `OFFSET` — implementation (helpers, composite cursors, `Page[T]`) is owned by the fastapi skill's Pagination section
- **AsyncSession isn't concurrent-safe**: never `asyncio.gather` (or otherwise interleave) operations on a shared session — concurrent use deadlocks or corrupts state. One session per concurrent task
- **Never check-then-insert.** A uniqueness or FK rule is enforced by the constraint and translated by `core/integrity.py`'s `guard()` ([ADR 0028](../../../docs/adr/0028-integrity-guard-constraint-identity-savepoint.md)), never by a SELECT before the INSERT. Postgres UPSERT (`on_conflict_do_update`, `on_conflict_do_nothing`) and `COPY` have no site in this schema today; the guarded flush is the answer here
- **Short transactions**: never `await` HTTP or external I/O inside an open transaction. Locks held during I/O serialize unrelated requests and pin connections from the async pool. Do the I/O first, then open the transaction for the write

## After a model change

Every model edit — a new table, a new column, a changed type — finishes here, and the sequence is three steps:

1. **Autogenerate** the revision: `uv run alembic revision --autogenerate -m "add scan_run table"`.
2. **Read what it wrote.** Autogenerate compares neither `ON DELETE` actions, CHECK bodies, GIN methods, nor partial predicates, so anything in that list is yours to write into the revision by hand.
3. **Roundtrip it**: `make migrate-roundtrip` upgrades, downgrades to the floor, and upgrades again. The floor is `DOWNGRADE_FLOOR` in the `Makefile`, where the person adding a migration reads it; CI's migration-drift job invokes that same target rather than carrying a copy of the value. It exercises the revisions above the floor, and runs as a test against an empty per-run test database the suite creates and drops around it — never `DATABASE_URL`, because the upgrade leg re-runs data repairs that no downgrade restores (`8b3a1162eb95` repeats the #97 `DELETE` over `score_snapshot`, and its `downgrade()` touches only indexes). `tests/migrations/test_downgrade_floor.py` fails if the floor ever resolves to the head, since a floor at the head downgrades across nothing.

Raise the floor whenever a migration lands whose `downgrade()` cannot restore its parent's schema — one that raises, or cannot run at all. The criterion is the schema, not the rows: a downgrade that puts the schema back but not the rows its upgrade deleted (`8b3a1162eb95`'s) still roundtrips, and the per-run database has no rows worth keeping. The floor is the shallowest schema-irreversible revision — the deepest one the roundtrip can reach — so it is downgraded *to* and never crossed, and everything above it stays schema-reversible. The current floor `b362121027a0` says it is irreversible by raising `NotImplementedError`, and its docstring names the rows its upgrade deleted. The `Makefile` comment beside `DOWNGRADE_FLOOR` carries the criterion and this floor's reason — read it before changing the value.

## Migration setup and commands

Migrations live in the `migrations/` directory (not `alembic/`). Setup: `env.py` builds the engine with `async_engine_from_config` and drives it from `run_async_migrations()`. Import all models so autogenerate detects them:
```python
from a11y_health.core.database import Base
from a11y_health.models import *  # noqa: F403

target_metadata = Base.metadata
```

Commands:
```bash
uv run alembic revision --autogenerate -m "add scan_run table"  # step 1 above; steps 2 and 3 still apply
uv run alembic revision -m "seed brand data"                    # manual SQL
uv run alembic upgrade head                                      # apply all pending
uv run alembic downgrade -1                                      # roll back one
```

- One migration per logical schema change
- Message format: verb + object (`"add scan_run table"`, `"add index on page_result.url"`)
- Data migrations use `op.execute()` with raw SQL, not ORM models
