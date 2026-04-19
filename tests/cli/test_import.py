import json
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.cli import NameResolutionError, NoDateDirsError, import_app
from a11y_health.models.enums import ScanRunStatus
from tests.factories import make_app_with_org_unit, make_axe_payload, make_brand, make_org_unit


async def test_import_creates_new_app_with_scan_run_per_date_subdir(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)

    app_dir = tmp_path / "any-directory-name"
    app_dir.mkdir()
    for date in ["2026-03-30", "2026-04-01"]:
        date_dir = app_dir / date
        date_dir.mkdir()
        payload = make_axe_payload(name="foo.com", url="https://foo.com/")
        payload["endTime"] = f"{date}T12:00:00Z"
        (date_dir / "page.json").write_text(json.dumps(payload))

    result = await import_app(
        db_client,
        directory=app_dir,
        org_unit_id=org_unit.id,
        brand_id=brand.id,
    )

    assert result.app_created is True
    assert result.app_slug == "foo.com"
    assert len(result.ingest_results) == 2

    resp = await db_client.get(f"/api/v1/apps/{result.app_id}")
    assert resp.status_code == 200
    app = resp.json()
    assert app["slug"] == "foo.com"
    assert app["name"] == "foo.com"
    assert app["org_unit_id"] == org_unit.id
    assert app["brand_id"] == brand.id

    for ingest_result in result.ingest_results:
        resp = await db_client.get(f"/api/v1/scan-runs/{ingest_result.scan_run_id}")
        assert resp.json()["status"] == ScanRunStatus.COMPLETED.value


async def test_import_no_date_subdirs_hard_fails_with_ingest_pointer(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)

    app_dir = tmp_path / "no-dates"
    app_dir.mkdir()
    (app_dir / "notes.txt").write_text("whatever")

    with pytest.raises(NoDateDirsError) as exc_info:
        await import_app(
            db_client,
            directory=app_dir,
            org_unit_id=org_unit.id,
            brand_id=brand.id,
        )

    assert "a11y ingest" in str(exc_info.value)

    resp = await db_client.get("/api/v1/apps/slug/no-dates")
    assert resp.status_code == 404


async def test_import_name_mismatch_across_date_subdirs_hard_fails(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)

    app_dir = tmp_path / "mismatch"
    app_dir.mkdir()

    (app_dir / "2026-03-30").mkdir()
    foo = make_axe_payload(name="foo.com", url="https://foo.com/")
    foo["endTime"] = "2026-03-30T12:00:00Z"
    (app_dir / "2026-03-30" / "p.json").write_text(json.dumps(foo))

    (app_dir / "2026-04-01").mkdir()
    bar = make_axe_payload(name="bar.com", url="https://bar.com/")
    bar["endTime"] = "2026-04-01T12:00:00Z"
    (app_dir / "2026-04-01" / "p.json").write_text(json.dumps(bar))

    with pytest.raises(NameResolutionError) as exc_info:
        await import_app(
            db_client,
            directory=app_dir,
            org_unit_id=org_unit.id,
            brand_id=brand.id,
        )

    message = str(exc_info.value)
    assert "foo.com" in message
    assert "bar.com" in message
    assert "2026-03-30" in message
    assert "2026-04-01" in message

    for slug in ("foo.com", "bar.com"):
        resp = await db_client.get(f"/api/v1/apps/slug/{slug}")
        assert resp.status_code == 404


async def test_import_warns_on_non_date_entries_and_continues(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)

    app_dir = tmp_path / "mixed"
    app_dir.mkdir()

    (app_dir / "2026-03-30").mkdir()
    payload = make_axe_payload(name="foo.com", url="https://foo.com/")
    payload["endTime"] = "2026-03-30T12:00:00Z"
    (app_dir / "2026-03-30" / "p.json").write_text(json.dumps(payload))

    (app_dir / "README.md").write_text("readme")
    (app_dir / "notes").mkdir()
    (app_dir / "2026-13-99").mkdir()

    messages: list[str] = []
    result = await import_app(
        db_client,
        directory=app_dir,
        org_unit_id=org_unit.id,
        brand_id=brand.id,
        on_progress=messages.append,
    )

    assert len(result.ingest_results) == 1

    joined = "\n".join(messages).lower()
    assert "skip" in joined or "warning" in joined
    assert "readme.md" in joined
    assert "notes" in joined
    assert "2026-13-99" in joined


async def test_import_reports_matched_app_and_scan_run_per_date(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    existing = await make_app_with_org_unit(db_session, slug="foo.com")

    app_dir = tmp_path / "anything"
    app_dir.mkdir()
    for date in ["2026-03-30", "2026-04-01"]:
        date_dir = app_dir / date
        date_dir.mkdir()
        payload = make_axe_payload(name="foo.com", url="https://foo.com/")
        payload["endTime"] = f"{date}T12:00:00Z"
        (date_dir / "p.json").write_text(json.dumps(payload))

    messages: list[str] = []
    result = await import_app(
        db_client,
        directory=app_dir,
        org_unit_id=existing.org_unit_id,
        brand_id=existing.brand_id,
        on_progress=messages.append,
    )

    assert result.app_created is False
    assert result.app_id == existing.id

    joined = "\n".join(messages).lower()
    assert "existing" in joined or "found" in joined or "matched" in joined
    assert "foo.com" in joined

    for ingest_result in result.ingest_results:
        assert any(str(ingest_result.scan_run_id) in m for m in messages)
    for date in ("2026-03-30", "2026-04-01"):
        assert any(date in m for m in messages)
