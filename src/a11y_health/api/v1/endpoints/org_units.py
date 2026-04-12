from datetime import UTC, datetime

from fastapi import APIRouter, Query

from a11y_health.api.deps import DbSession
from a11y_health.schemas.org_unit import OrgUnitCreate, OrgUnitRead, OrgUnitUpdate
from a11y_health.schemas.score_snapshot import ScoreSnapshotRead
from a11y_health.services import org_unit as org_unit_service
from a11y_health.services import score as score_service

router = APIRouter(prefix="/org-units", tags=["org-units"])


@router.post("", status_code=201)
async def create_org_unit(db: DbSession, data: OrgUnitCreate) -> OrgUnitRead:
    org_unit = await org_unit_service.create_org_unit(db, data)
    return OrgUnitRead.model_validate(org_unit)


@router.get("")
async def list_org_units(db: DbSession) -> list[OrgUnitRead]:
    org_units = await org_unit_service.list_org_units(db)
    return [OrgUnitRead.model_validate(ou) for ou in org_units]


@router.get("/{org_unit_id}")
async def get_org_unit(db: DbSession, org_unit_id: int) -> OrgUnitRead:
    org_unit = await org_unit_service.get_org_unit(db, org_unit_id)
    return OrgUnitRead.model_validate(org_unit)


@router.get("/{org_unit_id}/scores")
async def list_org_unit_scores(
    db: DbSession,
    org_unit_id: int,
    offset: int = 0,
    limit: int = Query(default=20, le=100),
) -> list[ScoreSnapshotRead]:
    snapshots = await score_service.list_org_unit_scores(db, org_unit_id, offset=offset, limit=limit)
    return [ScoreSnapshotRead.model_validate(s) for s in snapshots]


@router.get("/{org_unit_id}/ancestors")
async def get_ancestors(db: DbSession, org_unit_id: int) -> list[OrgUnitRead]:
    ancestors = await org_unit_service.get_ancestors(db, org_unit_id)
    return [OrgUnitRead.model_validate(a) for a in ancestors]


@router.get("/{org_unit_id}/descendants")
async def get_descendants(db: DbSession, org_unit_id: int) -> list[OrgUnitRead]:
    descendants = await org_unit_service.get_descendants(db, org_unit_id)
    return [OrgUnitRead.model_validate(d) for d in descendants]


@router.patch("/{org_unit_id}")
async def update_org_unit(db: DbSession, org_unit_id: int, data: OrgUnitUpdate) -> OrgUnitRead:
    old_parent_id = None
    if "parent_id" in data.model_fields_set:
        old_parent_id = (await org_unit_service.get_org_unit(db, org_unit_id)).parent_id
    updated = await org_unit_service.update_org_unit(db, org_unit_id, data)
    if "parent_id" in data.model_fields_set and updated.parent_id != old_parent_id:
        now = datetime.now(UTC)
        if old_parent_id is not None:
            await score_service.rollup_org_unit_scores(db, old_parent_id, now)
        if updated.parent_id is not None:
            await score_service.rollup_org_unit_scores(db, updated.parent_id, now)
    return OrgUnitRead.model_validate(updated)


@router.delete("/{org_unit_id}", status_code=204)
async def delete_org_unit(db: DbSession, org_unit_id: int) -> None:
    await org_unit_service.delete_org_unit(db, org_unit_id)
