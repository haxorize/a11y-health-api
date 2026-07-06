from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.schemas.axe_payload import parse_axe_payload
from a11y_health.services.page_result import create_page_result
from tests.factories import make_scan_run_with_parents


async def test_stored_raw_json_is_the_exact_uploaded_document(
    db_session: AsyncSession, axe_payload: dict[str, Any]
) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    axe_payload["toolVersion"] = "4.10.2"  # not modeled by the ingestion schema
    created = await create_page_result(db_session, scan_run.id, parse_axe_payload(axe_payload))

    await db_session.refresh(created, attribute_names=["raw_json"])
    assert created.raw_json == axe_payload
