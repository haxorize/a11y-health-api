from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import InvalidAxePayloadError, ScanRunCompletedError
from a11y_health.models.enums import ScanRunStatus
from a11y_health.services.page_result import create_page_result
from tests.factories import make_axe_payload, make_scan_run_with_parents


async def test_stored_raw_json_is_the_exact_uploaded_document(
    db_session: AsyncSession, axe_payload: dict[str, Any]
) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    axe_payload["toolVersion"] = "4.10.2"  # not modeled by the ingestion schema
    created = await create_page_result(db_session, scan_run.id, axe_payload)

    await db_session.refresh(created, attribute_names=["raw_json"])
    assert created.raw_json == axe_payload


async def test_invalid_document_is_the_invalid_axe_payload_mode(db_session: AsyncSession) -> None:
    # The service performs the one crossing itself, so the error mode is its
    # own — a caller handing it a raw dict never has to remember to parse.
    scan_run = await make_scan_run_with_parents(db_session)
    raw = make_axe_payload()
    del raw["findings"]

    with pytest.raises(InvalidAxePayloadError, match="findings"):
        await create_page_result(db_session, scan_run.id, raw)


async def test_completed_run_rejects_page_addition(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session, status=ScanRunStatus.COMPLETED)

    with pytest.raises(ScanRunCompletedError, match="completed"):
        await create_page_result(db_session, scan_run.id, make_axe_payload())
