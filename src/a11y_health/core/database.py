"""Database engine, session factory, and the ORM base classes.

`get_db()` is the per-request session dependency: one transaction per request,
committed on success and rolled back on any exception, so services never call
`commit()` themselves.

See `docs/architecture.md` ("How the database session and transactions work").
"""

import enum
from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from a11y_health.config import settings


# The Postgres enum labels are the members' values, not their names. The
# migrations created each enum type with these labels, so every `Enum` column
# passes this as `values_callable`; without it SQLAlchemy persists the member
# names, which the existing types reject at insert.
def enum_values(e: type[enum.Enum]) -> list[str]:
    return [m.value for m in e]


engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
