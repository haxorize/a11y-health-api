from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import InvalidAxePayloadError, ScanRunCompletedError
from a11y_health.models.enums import ScanRunStatus
from a11y_health.models.page_result import PageResult
from a11y_health.services.page_result import create_page_result
from tests.factories import make_axe_payload, make_scan_run_with_parents, recorded_statements


async def test_stored_raw_json_is_the_exact_uploaded_document(
    db_session: AsyncSession, axe_payload: dict[str, Any]
) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    axe_payload["toolVersion"] = "4.10.2"  # not modeled by the ingestion schema
    created = await create_page_result(db_session, scan_run.id, axe_payload)

    await db_session.refresh(created, attribute_names=["raw_json"])
    assert created.raw_json == axe_payload


# Reds if the create path re-reads its row: the INSERT's RETURNING carries the
# timestamps, so the write is the Scan Run's locked read, the page result's
# insert, and a rule-finding and a node-finding insert for each finding type
# the fixture carries. The read is pinned first, so a re-read cannot stand in
# for a Scan Run read the identity map answered unlocked.
async def test_create_page_result_takes_its_timestamps_from_the_insert(
    db_session: AsyncSession, axe_payload: dict[str, Any]
) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    async with recorded_statements(db_session) as statements:
        page_result = await create_page_result(db_session, scan_run.id, axe_payload)
    returned = (page_result.created_at, page_result.updated_at)

    assert len(statements) == 6
    assert statements[0].startswith("SELECT") and statements[0].endswith("FOR SHARE")
    assert not [statement for statement in statements[1:] if statement.startswith("SELECT")]
    stored = await db_session.execute(
        select(PageResult.created_at, PageResult.updated_at).where(PageResult.id == page_result.id)
    )
    assert returned == tuple(stored.one())


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
