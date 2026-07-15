from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.database import get_db

# scope="function" commits before the response is sent (default "request"
# scope commits after). Post-response commit races the client's next request:
# a sequential POST-then-GET can 404 on the row the POST just returned.
DbSession = Annotated[AsyncSession, Depends(get_db, scope="function")]
