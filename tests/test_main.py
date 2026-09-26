from collections import Counter

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from a11y_health.core.database import SessionSource, bind_session_source
from a11y_health.main import app, assemble_application

_ELSEWHERE = "https://elsewhere.example"


def test_every_operation_id_in_the_generated_document_is_distinct() -> None:
    # FastAPI answers a collision with a UserWarning and writes both, and the
    # UI's codegen then keys one method on two operations. Red when two route
    # functions share a name, e.g. `list_scan_run_pages` renamed to
    # `list_findings`.
    operations = [op for path in app.openapi()["paths"].values() for op in path.values()]
    counts = Counter(op["operationId"] for op in operations)

    assert len(operations) > 0
    assert [op_id for op_id, n in counts.items() if n > 1] == []


# With credentials allowed, a wildcard cannot be sent back as `*` (the Fetch
# spec refuses it), so an allowed origin is echoed; an origin outside a fixed
# list is refused at preflight.
@pytest.mark.parametrize(
    ("allowed_origins", "status", "allow_origin"),
    [
        (["*"], 200, _ELSEWHERE),
        (["http://localhost:3000"], 400, None),
    ],
    ids=["wildcard", "fixed-list"],
)
async def test_the_assembled_application_answers_a_preflight_by_its_allowed_origins(
    allowed_origins: list[str], status: int, allow_origin: str | None
) -> None:
    transport = ASGITransport(app=assemble_application(allowed_origins=allowed_origins))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.options(
            "/api/v1/health",
            headers={"Origin": _ELSEWHERE, "Access-Control-Request-Method": "GET"},
        )

    assert response.status_code == status
    assert response.headers.get("access-control-allow-origin") == allow_origin
    assert response.headers["access-control-allow-credentials"] == "true"


async def test_startup_probes_the_bound_engine_and_shutdown_disposes_it(engine: AsyncEngine) -> None:
    # An engine of its own on the per-run database, so the dispose lands on a
    # pool no other test holds.
    probed = create_async_engine(engine.url)
    assembled = assemble_application(allowed_origins=[])
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        statements.append(statement)

    event.listen(probed.sync_engine, "before_cursor_execute", record)
    try:
        with bind_session_source(SessionSource(probed)):
            async with assembled.router.lifespan_context(assembled):
                pool_while_serving = probed.pool
                assert statements == ["SELECT 1"]
            assert probed.pool is not pool_while_serving
    finally:
        event.remove(probed.sync_engine, "before_cursor_execute", record)
        await probed.dispose()
