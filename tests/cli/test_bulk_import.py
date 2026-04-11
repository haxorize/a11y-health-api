import json
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.cli import bulk_import
from tests.factories import make_app_with_org_unit, make_axe_payload, make_org_unit


async def test_bulk_import_creates_scan_run_per_date_directory(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)

    # Create top-level app directory with two date subdirectories
    app_dir = tmp_path / "my-app"
    app_dir.mkdir()
    for date in ["2026-03-30", "2026-04-01"]:
        date_dir = app_dir / date
        date_dir.mkdir()
        payload = make_axe_payload(url="https://example.com")
        payload["endTime"] = f"{date}T12:00:00Z"
        (date_dir / "page.json").write_text(json.dumps(payload))

    result = await bulk_import(
        db_client,
        directory=app_dir,
        org_unit_id=org_unit.id,
        brand="Humana",
    )

    assert len(result.upload_results) == 2
    assert result.app_created is True

    # App was created with slug as display name
    resp = await db_client.get(f"/api/v1/apps/{result.app_id}")
    assert resp.status_code == 200
    app = resp.json()
    assert app["slug"] == "my-app"
    assert app["name"] == "my-app"
    assert app["org_unit_id"] == org_unit.id

    # Each date directory produced a completed scan run
    for upload_result in result.upload_results:
        resp = await db_client.get(f"/api/v1/scan-runs/{upload_result.scan_run_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"


async def test_bulk_import_reuses_existing_app(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    existing_app = await make_app_with_org_unit(db_session, slug="existing-app")

    app_dir = tmp_path / "existing-app"
    app_dir.mkdir()
    date_dir = app_dir / "2026-03-30"
    date_dir.mkdir()
    payload = make_axe_payload(url="https://example.com")
    payload["endTime"] = "2026-03-30T12:00:00Z"
    (date_dir / "page.json").write_text(json.dumps(payload))

    result = await bulk_import(
        db_client,
        directory=app_dir,
        org_unit_id=existing_app.org_unit_id,
        brand="Humana",
    )

    assert result.app_id == existing_app.id
    assert result.app_created is False
    assert len(result.upload_results) == 1


async def test_bulk_import_uses_brand_for_auto_created_app(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)

    app_dir = tmp_path / "go365-app"
    app_dir.mkdir()
    date_dir = app_dir / "2026-03-30"
    date_dir.mkdir()
    payload = make_axe_payload(url="https://example.com")
    payload["endTime"] = "2026-03-30T12:00:00Z"
    (date_dir / "page.json").write_text(json.dumps(payload))

    result = await bulk_import(
        db_client,
        directory=app_dir,
        org_unit_id=org_unit.id,
        brand="Go365",
    )

    resp = await db_client.get(f"/api/v1/apps/{result.app_id}")
    assert resp.json()["brand"] == "Go365"


async def test_bulk_import_skips_non_date_subdirectories(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)

    app_dir = tmp_path / "my-app"
    app_dir.mkdir()

    # Valid date directory
    date_dir = app_dir / "2026-03-30"
    date_dir.mkdir()
    payload = make_axe_payload(url="https://example.com")
    payload["endTime"] = "2026-03-30T12:00:00Z"
    (date_dir / "page.json").write_text(json.dumps(payload))

    # Non-date directories that should be skipped
    (app_dir / "not-a-date").mkdir()
    (app_dir / "2026-13-99").mkdir()
    (app_dir / "README.md").write_text("ignore me")

    result = await bulk_import(
        db_client,
        directory=app_dir,
        org_unit_id=org_unit.id,
        brand="Humana",
    )

    assert len(result.upload_results) == 1
