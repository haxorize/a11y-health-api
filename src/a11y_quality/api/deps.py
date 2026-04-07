from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_quality.core.database import get_db

SessionDep = Annotated[AsyncSession, Depends(get_db)]
