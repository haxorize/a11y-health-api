---
name: database
description: Database conventions for this project (PostgreSQL schema design + SQLAlchemy ORM). Use when creating or editing models, defining columns, choosing data types, writing migrations, or adding indexes/constraints.
---

# Database Conventions

## Data types

- **IDs**: `BIGINT GENERATED ALWAYS AS IDENTITY` for PKs; `UUID` only when opacity or federation is needed
- **Strings**: `TEXT` always; enforce length with `CHECK (LENGTH(col) <= n)`, never `VARCHAR(n)` or `CHAR(n)`
- **Timestamps**: `TIMESTAMPTZ` always, never `TIMESTAMP`; default `now()` for creation times
- **Money/precision**: `NUMERIC(p,s)` for financial or precision-critical values; `FLOAT` is fine for informational ratios and scores
- **Booleans**: `BOOLEAN NOT NULL` unless tri-state is intentional
- **JSON**: `JSONB` with GIN index; only for optional/semi-structured attributes

### Do not use

`timestamp` (without tz), `char(n)`, `varchar(n)`, `money`, `timetz`, `serial`

## Model definition

Models in `src/a11y_health/models/` inherit from `core.database.Base`. `Base` provides `id` (BIGINT IDENTITY PK). Mutable tables also inherit `TimestampMixin` for `created_at`/`updated_at`:

```python
from sqlalchemy import Enum, Text
from sqlalchemy.orm import Mapped, mapped_column
from a11y_health.core.database import Base, TimestampMixin, enum_values
from a11y_health.models.enums import ScanStatus

class Scan(TimestampMixin, Base):
    __tablename__ = "scan"
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ScanStatus] = mapped_column(
        Enum(ScanStatus, name="scan_status", values_callable=enum_values), nullable=False
    )
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

## Relationships

Do not use `relationship()`. Use explicit FK columns only. This avoids lazy-load pitfalls with async sessions.

## Deferred columns

Use `deferred()` for large columns (e.g., JSONB payloads) that should not be loaded in default queries:
```python
from sqlalchemy.orm import deferred

raw_json: Mapped[dict[str, Any]] = deferred(mapped_column(JSONB, nullable=False))
```

Omit deferred columns from Pydantic Read schemas — they are not loaded by default queries.

## Alembic migrations

Migrations live in the `migrations/` directory (not `alembic/`). Setup: `env.py` uses `run_async` with `create_async_engine`. Import all models so autogenerate detects them:
```python
from a11y_health.core.database import Base
from a11y_health.models import *  # noqa: F403
target_metadata = Base.metadata
```

Commands:
```bash
alembic revision --autogenerate -m "add scan table"  # from model changes
alembic revision -m "seed brand data"                # manual SQL
alembic upgrade head                                  # apply all pending
alembic downgrade -1                                  # roll back one
```

- One migration per logical schema change
- Message format: verb + object (`"add scan table"`, `"add index on page.url"`)
- Always review autogenerated output before applying
- Data migrations use `op.execute()` with raw SQL, not ORM models
- Test with `alembic downgrade base && alembic upgrade head`
