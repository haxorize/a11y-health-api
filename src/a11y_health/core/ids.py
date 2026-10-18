from typing import Annotated

from pydantic import Field

# The range of a bigint identity (ADR 0001), so an id outside it is the
# framework's 422 rather than an asyncpg overflow. ADR 0050 records why the
# floor is 1, not 0.
BIGINT_MAX = 2**63 - 1

# The identity range for request ids only: path, body and query. Read schemas
# keep `int`, since a bound on a response validates nothing a client sends.
EntityId = Annotated[int, Field(ge=1, le=BIGINT_MAX)]
