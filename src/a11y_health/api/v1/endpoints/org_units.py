import uuid

from fastapi import APIRouter, HTTPException, Query

from a11y_health.api.deps import DbSession
from a11y_health.core.exceptions import NotFoundError
from a11y_health.schemas.org_unit import OrgUnitCreate, OrgUnitRead, OrgUnitUpdate
from a11y_health.services import org_unit as org_unit_service

router = APIRouter(prefix="/org-units", tags=["org-units"])


@router.post("", status_code=201)
async def create_org_unit(db: DbSession, data: OrgUnitCreate) -> OrgUnitRead:
    try:
        org_unit = await org_unit_service.create_org_unit(db, data)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return OrgUnitRead.model_validate(org_unit)


@router.get("")
async def list_org_units(
    db: DbSession,
    offset: int = 0,
    limit: int = Query(default=20, le=100),
) -> list[OrgUnitRead]:
    org_units = await org_unit_service.list_org_units(db, offset=offset, limit=limit)
    return [OrgUnitRead.model_validate(ou) for ou in org_units]


@router.get("/{org_unit_id}")
async def get_org_unit(db: DbSession, org_unit_id: uuid.UUID) -> OrgUnitRead:
    try:
        org_unit = await org_unit_service.get_org_unit(db, org_unit_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return OrgUnitRead.model_validate(org_unit)


@router.patch("/{org_unit_id}")
async def update_org_unit(db: DbSession, org_unit_id: uuid.UUID, data: OrgUnitUpdate) -> OrgUnitRead:
    try:
        updated = await org_unit_service.update_org_unit(db, org_unit_id, data)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return OrgUnitRead.model_validate(updated)


@router.delete("/{org_unit_id}", status_code=204)
async def delete_org_unit(db: DbSession, org_unit_id: uuid.UUID) -> None:
    try:
        await org_unit_service.delete_org_unit(db, org_unit_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
