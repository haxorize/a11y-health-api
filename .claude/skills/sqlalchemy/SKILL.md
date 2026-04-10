---
name: sqlalchemy
description: SQLAlchemy ORM model conventions for this project. Use when creating or editing models in models/, defining columns, mixins, or relationships.
---

# SQLAlchemy Model Conventions

## Model definition

Models in `src/a11y_health/models/` inherit from `core.database.Base`. `Base` provides `id` (BIGINT IDENTITY PK). Mutable tables also inherit `TimestampMixin` for `created_at`/`updated_at`. For enum columns, use `enum_values` (also from `core.database`) as the `values_callable`:

```python
from sqlalchemy import Enum, Text
from sqlalchemy.orm import Mapped, mapped_column
from a11y_health.core.database import Base, TimestampMixin, enum_values

class Scan(TimestampMixin, Base):
    __tablename__ = "scan"
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ScanStatus] = mapped_column(
        Enum(ScanStatus, name="scan_status", values_callable=enum_values), nullable=False
    )
```

Use `Mapped` type annotations on all columns for type checker compatibility.

## Models package

Re-export all ORM model classes in `models/__init__.py` with `__all__`. This ensures Alembic autogenerate and the test conftest's `from a11y_health.models import *` discover all tables.

## Table args

Use a plain tuple for `__table_args__` — no trailing `{}` dict:
```python
__table_args__ = (
    UniqueConstraint("slug", name=UQ_APP_SLUG),
    Index("ix_app_org_unit_id", "org_unit_id"),
)
```

## Relationships

Do not use `relationship()`. Use explicit FK columns only. This avoids lazy-load pitfalls with async sessions.

## Deferred columns

Use `deferred()` for large columns (e.g., JSONB payloads) that should not be loaded in default queries:
```python
from sqlalchemy.orm import deferred

raw_json: Mapped[dict[str, Any]] = deferred(mapped_column(JSONB, nullable=False))
```

Omit deferred columns from Pydantic Read schemas — they are not loaded by default queries.
