---
name: database
description: Database conventions for this project (PostgreSQL schema design + SQLAlchemy ORM, plus query patterns). Use when creating or editing models, defining columns, choosing data types, writing migrations, adding indexes/constraints, or writing services and queries that hit the database.
---

# Database Conventions

## Data types

- **IDs**: `BIGINT GENERATED ALWAYS AS IDENTITY` for PKs; `UUID` only when opacity or federation is needed
- **Strings**: `TEXT` always; enforce length with `CHECK (LENGTH(col) <= n)`, never `VARCHAR(n)` or `CHAR(n)`
- **Timestamps**: `TIMESTAMPTZ` always, never `TIMESTAMP`; default `now()` for creation times. In SQLAlchemy ORM, use `DateTime(timezone=True)` — it maps to `TIMESTAMPTZ` in PostgreSQL
- **Money/precision**: `NUMERIC(p,s)` for financial or precision-critical values; `FLOAT` is fine for informational ratios and scores
- **Booleans**: `BOOLEAN NOT NULL` unless tri-state is intentional
- **JSON**: `JSONB` with GIN index; only for optional/semi-structured attributes

### Do not use

`timestamp` (without tz), `char(n)`, `varchar(n)`, `money`, `timetz`, `serial`

## Model definition

Models in `src/a11y_health/models/` inherit from `core.database.Base`. `Base` provides `id` (BIGINT IDENTITY PK). Mutable tables also inherit `TimestampMixin` for `created_at`/`updated_at`:

```python
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from a11y_health.core.database import Base, TimestampMixin, enum_values
from a11y_health.models.enums import ScanRunStatus


class ScanRun(TimestampMixin, Base):
    __tablename__ = "scan_run"
    app_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[ScanRunStatus] = mapped_column(
        Enum(ScanRunStatus, name="scan_run_status", values_callable=enum_values), nullable=False
    )
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

Use `Mapped` type annotations on all columns for type checker compatibility.

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

- `snake_case` for all identifiers; never quote identifiers
- `NOT NULL` everywhere semantically required
- Singular table names matching the resource (`scan`, `rule`, `page`)
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
- **UNIQUE**: use `NULLS NOT DISTINCT` (PG15+) unless multiple NULLs are intentional
- **CHECK**: combine with `NOT NULL` since NULLs pass checks
- **Naming**: explicitly name all constraints (`ck_<table>_<col>_<desc>`, `uq_<table>_<col>`, `ix_<table>_<col>`). Export constraint names as module-level constants (e.g., `UQ_APP_SLUG`, `CK_ORG_UNIT_NAME_LENGTH`) for matching in `IntegrityError` handlers

## Indexes

- **Composite indexes** follow the leftmost-prefix rule — equality columns first, range columns last. `(status, scanned_at)` serves `WHERE status = ? AND scanned_at > ?` and `WHERE status = ?`, but not `WHERE scanned_at > ?` alone. Prefer one composite over two singletons when queries `AND` the columns
- **Partial indexes** when queries consistently filter on the same predicate (status, soft-delete, non-null):
  ```python
  from sqlalchemy import text
  Index("ix_scan_run_pending_scanned_at", "scanned_at", postgresql_where=text("status = 'pending'"))
  ```
- **Covering indexes (`INCLUDE`)** for hot read paths to enable index-only scans:
  ```python
  Index("ix_app_slug", "slug", postgresql_include=["name", "org_unit_id"])
  ```
- **Index type by data**:
  - B-tree (default): equality, ranges, ordering
  - GIN: `JSONB` containment (`@>`, `?`), arrays, full-text
  - BRIN: large append-only time-series columns (10–100x smaller than B-tree); good fit for monotonically growing `scanned_at`-style columns once the table is large
  - Avoid GiST/Hash unless there's a specific reason

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
- **UPSERT** for idempotent ingest, not check-then-insert (race condition):
  ```python
  from sqlalchemy.dialects.postgresql import insert
  stmt = insert(App).values(rows)
  stmt = stmt.on_conflict_do_update(
      index_elements=["slug"],
      set_={"name": stmt.excluded.name},
  )
  await session.execute(stmt)
  ```
  Use `on_conflict_do_nothing(...)` for insert-or-skip. Conflict target must match a UNIQUE or PK constraint
- **Batch inserts** in ingest — never loop single-row INSERTs. `session.execute(insert(Model), list_of_dicts)` issues one statement per chunk; for very large loads use `COPY`
- **Cursor pagination** for list endpoints, not `OFFSET` (OFFSET scans all skipped rows; degrades on deep pages). Order by an indexed key and pass the last value back as the next cursor:
  ```python
  q = select(ScanRun).where(ScanRun.id > cursor).order_by(ScanRun.id).limit(limit)
  ```
  Multi-column sort: the cursor must include all sort columns — `WHERE (created_at, id) > (:cursor_ts, :cursor_id)` ordered by `(created_at, id)`
- **AsyncSession isn't concurrent-safe**: never `asyncio.gather` (or otherwise interleave) operations on a shared session — concurrent use deadlocks or corrupts state. One session per concurrent task
- **Short transactions**: never `await` HTTP or external I/O inside an open transaction. Locks held during I/O serialize unrelated requests and pin connections from the async pool. Do the I/O first, then open the transaction for the write

## Alembic migrations

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
- Always review autogenerated output before applying
- Data migrations use `op.execute()` with raw SQL, not ORM models
- Test with `uv run alembic downgrade <floor> && uv run alembic upgrade head`, where `<floor>` is the newest irreversible migration (pinned as `DOWNGRADE_FLOOR` in CI's migration-drift job). An irreversible migration (e.g. a one-time data repair) raises `NotImplementedError` in `downgrade()` and becomes the new floor; everything above the floor must stay reversible
