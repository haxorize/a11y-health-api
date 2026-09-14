---
name: database
description: Database conventions for this project (PostgreSQL schema design + SQLAlchemy ORM, plus query patterns). Use when creating or editing models, defining columns, choosing data types, writing migrations, adding indexes/constraints, or writing services and queries that hit the database.
---

# Database Conventions

## Data types

- **IDs**: `BIGINT GENERATED ALWAYS AS IDENTITY` for PKs; `UUID` only when opacity or federation is needed
- **Strings**: `TEXT` always; enforce length with `CHECK (LENGTH(col) <= n)`, never `VARCHAR(n)` or `CHAR(n)`
- **Timestamps**: `TIMESTAMPTZ` always, never `TIMESTAMP`; default `now()` for creation times. In SQLAlchemy ORM, use `DateTime(timezone=True)` — it maps to `TIMESTAMPTZ` in PostgreSQL
- **Booleans**: `BOOLEAN NOT NULL` unless tri-state is intentional
- **Scores and ratios**: `FLOAT`. Nothing here is financial, so `NUMERIC` has no site in this schema
- **JSON**: `JSONB`. GIN only on a column a query filters (`rule_finding.wcag_criteria`, `rule_finding.classifications`); a payload column is `deferred()` and unindexed ([ADR 0008](../../../docs/adr/0008-defer-jsonb-by-access-pattern.md)), which is why `page_result.raw_json` and `node_finding.checks` carry no index

### Do not use

`timestamp` (without tz), `char(n)`, `varchar(n)`, `money`, `timetz`, `serial`

## Model definition

Models in `src/a11y_health/models/` inherit from `core.database.Base`. `Base` provides `id` (BIGINT IDENTITY PK). Mutable tables also inherit `TimestampMixin` for `created_at`/`updated_at`.

Declare every constraint name as a module-level constant and give every `ForeignKey` a `name=`, including the ones autogenerate would name for you — the auto-generated `<table>_<col>_fkey` cannot be mapped in an `integrity.guard` call, and changing its `ON DELETE` later costs a rename migration first. `models/app.py` is the worked example:

```python
UQ_APP_SLUG = "uq_app_slug"
CK_APP_NAME_LENGTH = "ck_app_name_length"
FK_APP_ORG_UNIT_ID = "fk_app_org_unit_id"


class App(TimestampMixin, Base):
    __tablename__ = "app"
    __table_args__ = (
        CheckConstraint("LENGTH(name) <= 255", name=CK_APP_NAME_LENGTH),
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
- **FK**: always specify `ON DELETE` action; always add an explicit index on the FK column (Postgres does not auto-index FKs). Use `RESTRICT` for parent/reference relationships and `CASCADE` for owned children that should be deleted with their parent
- **UNIQUE**: a uniqueness rule that holds only for some rows is a partial unique `Index`, not a `UniqueConstraint` — see `UQ_SCORE_SNAPSHOT_ORG_UNIT_SNAPSHOT_AT` and `UQ_ORG_UNIT_SINGLE_ROOT`, both of which exist because the column is nullable
- **CHECK**: combine with `NOT NULL` since NULLs pass checks
- **Naming**: explicitly name all constraints (`ck_<table>_<col>_<desc>`, `uq_<table>_<col>`, `ix_<table>_<col>`, `fk_<table>_<col>`). Export constraint names as module-level constants (e.g., `UQ_APP_SLUG`, `FK_APP_ORG_UNIT_ID`) for the constraint→error mappings passed to `integrity.guard` (see the fastapi skill's Services section)

## Indexes

The repo uses three index kinds — plain B-tree (every FK column), composite, and GIN. A fourth kind is an ADR, not a judgment call at the model.

- **Composite**: equality columns first, range columns last; prefer one composite over two singletons when queries `AND` the columns (`ix_rule_finding_page_result_id_type`, `ix_page_result_scan_run_id_id`)
- **Partial**, via `postgresql_where`, when the predicate is what makes the rule true — both sites are uniqueness over a nullable column:
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
- **Every index is built non-concurrently.** `migrations/env.py` wraps each revision in one transaction and `CREATE INDEX CONCURRENTLY` cannot run inside one, so a new index on `rule_finding` or `page_result` holds a `SHARE` lock against ingest for the whole build. Adding one to a large table needs an autocommit escape hatch in `env.py` first; the existing indexes were all applied when the tables were small

## Relationships

Do not use `relationship()`. Use explicit FK columns only. This avoids lazy-load pitfalls with async sessions.

## Deferred columns

Use `deferred()` for large columns (e.g., JSONB payloads) that should not be loaded in default queries:
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
- **Batch inserts** in ingest — never loop single-row INSERTs. `session.execute(insert(Model), list_of_dicts)` issues one statement per chunk
- **Cursor/keyset pagination** for list endpoints, never `OFFSET` — implementation (helpers, composite cursors, `Page[T]`) is owned by the fastapi skill's Pagination section
- **AsyncSession isn't concurrent-safe**: never `asyncio.gather` (or otherwise interleave) operations on a shared session — concurrent use deadlocks or corrupts state. One session per concurrent task
- **Short transactions**: never `await` HTTP or external I/O inside an open transaction. Locks held during I/O serialize unrelated requests and pin connections from the async pool. Do the I/O first, then open the transaction for the write

## After a model change

Every model edit — a new table, a new column, a changed type — finishes here, and the sequence is three steps:

1. **Autogenerate** the revision: `uv run alembic revision --autogenerate -m "add scan_run table"`.
2. **Read what it wrote.** Autogenerate compares neither `ON DELETE` actions, CHECK bodies, GIN methods, nor partial predicates, so anything in that list is yours to write into the revision by hand.
3. **Roundtrip it**: `make migrate-roundtrip` upgrades, downgrades to the floor, and upgrades again. The floor is `DOWNGRADE_FLOOR` in the `Makefile`, where the person adding a migration reads it; CI's migration-drift job invokes that same target rather than carrying a copy of the value.

An irreversible migration (e.g. a one-time data repair) raises `NotImplementedError` in `downgrade()` and becomes the new floor; everything above the floor must stay reversible.

Migrations live in the `migrations/` directory (not `alembic/`). Setup: `env.py` uses `run_async` with `create_async_engine`. Import all models so autogenerate detects them:
```python
from a11y_health.core.database import Base
from a11y_health.models import *  # noqa: F403

target_metadata = Base.metadata
```

Commands:
```bash
uv run alembic revision --autogenerate -m "add scan_run table"  # from model changes
uv run alembic revision -m "seed brand data"                    # manual SQL
uv run alembic upgrade head                                      # apply all pending
uv run alembic downgrade -1                                      # roll back one
```

- One migration per logical schema change
- Message format: verb + object (`"add scan_run table"`, `"add index on page_result.url"`)
- Data migrations use `op.execute()` with raw SQL, not ORM models
