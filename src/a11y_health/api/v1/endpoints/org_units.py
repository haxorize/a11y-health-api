from typing import Annotated

from fastapi import APIRouter, Query

from a11y_health.api.deps import DbSession
from a11y_health.core.error_contract import ErrorCode, error_responses
from a11y_health.core.pagination import OrderParam, Page, PageParams
from a11y_health.models.enums import ScoreSnapshotOwnerType
from a11y_health.schemas.org_unit import OrgUnitCreate, OrgUnitRead, OrgUnitUpdate
from a11y_health.schemas.score_snapshot import ScoreSnapshotRead
from a11y_health.services import org_unit as org_unit_service
from a11y_health.services import owner as owner_service

router = APIRouter(prefix="/org-units", tags=["org-units"])


@router.post("", status_code=201, responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.DUPLICATE_ROOT))
async def create_org_unit(db: DbSession, data: OrgUnitCreate) -> OrgUnitRead:
    org_unit = await org_unit_service.create_org_unit(db, data)
    return OrgUnitRead.model_validate(org_unit)


@router.get("")
async def list_org_units(
    db: DbSession,
    parent_id: Annotated[list[int] | None, Query()] = None,
) -> list[OrgUnitRead]:
    org_units = await org_unit_service.list_org_units(db, parent_id=parent_id)
    return [OrgUnitRead.model_validate(ou) for ou in org_units]


@router.get("/{org_unit_id}", responses=error_responses(ErrorCode.NOT_FOUND))
async def get_org_unit(db: DbSession, org_unit_id: int) -> OrgUnitRead:
    org_unit = await org_unit_service.get_org_unit(db, org_unit_id)
    return OrgUnitRead.model_validate(org_unit)


@router.get("/{org_unit_id}/scores", responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.INVALID_CURSOR))
async def list_org_unit_scores(
    db: DbSession,
    org_unit_id: int,
    pagination: PageParams,
    order: OrderParam,
) -> Page[ScoreSnapshotRead]:
    page = await owner_service.list_scores(
        db,
        ScoreSnapshotOwnerType.ORG_UNIT,
        org_unit_id,
        cursor=pagination.cursor,
        limit=pagination.limit,
        descending=order.descending,
    )
    return Page.from_cursor_page(page, ScoreSnapshotRead.model_validate)


@router.get("/{org_unit_id}/ancestors", responses=error_responses(ErrorCode.NOT_FOUND))
async def get_ancestors(db: DbSession, org_unit_id: int) -> list[OrgUnitRead]:
    ancestors = await org_unit_service.get_ancestors(db, org_unit_id)
    return [OrgUnitRead.model_validate(a) for a in ancestors]


@router.patch(
    "/{org_unit_id}",
    responses=error_responses(
        ErrorCode.NOT_FOUND, ErrorCode.CIRCULAR_REFERENCE, ErrorCode.DUPLICATE_ROOT, ErrorCode.CONCURRENT_ROLLUP
    ),
)
async def update_org_unit(db: DbSession, org_unit_id: int, data: OrgUnitUpdate) -> OrgUnitRead:
    updated = await org_unit_service.update_org_unit(db, org_unit_id, data)
    return OrgUnitRead.model_validate(updated)


@router.delete(
    "/{org_unit_id}", status_code=204, responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.HAS_DEPENDENTS)
)
async def delete_org_unit(db: DbSession, org_unit_id: int) -> None:
    await org_unit_service.delete_org_unit(db, org_unit_id)
