import json
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.cli._operations import NameOverrideMismatchError, import_app
from a11y_health.cli._scan import NameResolutionError, NoDateDirsError, UnderivableAppNameError
from a11y_health.models.enums import ScanRunStatus
from tests.factories import make_app_with_org_unit, make_axe_payload, make_brand, make_org_unit, write_scan_file


def _write_scan_dir(app_dir: Path, date: str, *, name: str, end_time: str | None = None) -> None:
    date_dir = app_dir / date
    date_dir.mkdir()
    # `is not None`, not `or`: an explicit "" is a real case — `_parse_scanned_at`
    # treats it as absent and falls back to the directory mtime.
    write_scan_file(date_dir, "p.json", name=name, end_time=end_time if end_time is not None else f"{date}T12:00:00Z")


async def test_import_creates_new_app_with_scan_run_per_date_subdir(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)

    app_dir = tmp_path / "any-directory-name"
    app_dir.mkdir()
    for date in ["2026-03-30", "2026-04-01"]:
        _write_scan_dir(app_dir, date, name="foo.com")

    result = await import_app(
        db_client,
        directory=app_dir,
        org_unit_id=org_unit.id,
        brand_id=brand.id,
    )

    assert result.app_created is True
    assert result.app_slug == "foo-com"
    assert len(result.ingest_results) == 2

    resp = await db_client.get(f"/api/v1/apps/{result.app_id}")
    assert resp.status_code == 200
    app = resp.json()
    assert app["slug"] == "foo-com"
    assert app["name"] == "foo.com"
    assert app["org_unit_id"] == org_unit.id
    assert app["brand_id"] == brand.id

    for ingest_result in result.ingest_results:
        resp = await db_client.get(f"/api/v1/scan-runs/{ingest_result.scan_run_id}")
        assert resp.json()["status"] == ScanRunStatus.COMPLETED.value


async def test_import_same_directory_twice_resolves_one_app(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)

    app_dir = tmp_path / "repeat"
    app_dir.mkdir()
    _write_scan_dir(app_dir, "2026-03-30", name="foo.com")

    first = await import_app(db_client, directory=app_dir, org_unit_id=org_unit.id, brand_id=brand.id)
    second = await import_app(db_client, directory=app_dir, org_unit_id=org_unit.id, brand_id=brand.id)

    assert first.app_created is True
    assert second.app_created is False
    assert second.app_id == first.app_id

    resp = await db_client.get("/api/v1/apps")
    assert len(resp.json()["items"]) == 1


async def test_import_matches_app_created_via_api_with_derivation_equivalent_name(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)

    resp = await db_client.post(
        "/api/v1/apps",
        json={"name": "Foo. Com", "brand_id": brand.id, "org_unit_id": org_unit.id},
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["slug"] == "foo-com"

    app_dir = tmp_path / "equivalent"
    app_dir.mkdir()
    _write_scan_dir(app_dir, "2026-03-30", name="foo.com")

    result = await import_app(db_client, directory=app_dir, org_unit_id=org_unit.id, brand_id=brand.id)

    assert result.app_created is False
    assert result.app_id == created["id"]

    resp = await db_client.get("/api/v1/apps")
    assert len(resp.json()["items"]) == 1


async def test_import_name_override_sets_app_name_at_creation(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)

    app_dir = tmp_path / "pretty"
    app_dir.mkdir()
    _write_scan_dir(app_dir, "2026-03-30", name="humana-com")

    result = await import_app(
        db_client, directory=app_dir, org_unit_id=org_unit.id, brand_id=brand.id, name="Humana.com"
    )

    assert result.app_created is True
    resp = await db_client.get(f"/api/v1/apps/{result.app_id}")
    app = resp.json()
    assert app["name"] == "Humana.com"
    assert app["slug"] == "humana-com"

    again = await import_app(db_client, directory=app_dir, org_unit_id=org_unit.id, brand_id=brand.id)
    assert again.app_created is False
    assert again.app_id == result.app_id


async def test_import_name_override_not_derivation_equivalent_hard_fails(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)

    app_dir = tmp_path / "mismatched-override"
    app_dir.mkdir()
    _write_scan_dir(app_dir, "2026-03-30", name="humana-com")

    with pytest.raises(NameOverrideMismatchError) as exc_info:
        await import_app(db_client, directory=app_dir, org_unit_id=org_unit.id, brand_id=brand.id, name="Other Site")

    message = str(exc_info.value)
    assert "other-site" in message
    assert "humana-com" in message

    resp = await db_client.get("/api/v1/apps")
    assert resp.json()["items"] == []


async def test_import_name_override_on_existing_app_warns_and_continues(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    existing = await make_app_with_org_unit(db_session, app_name="humana-com", slug="humana-com")

    app_dir = tmp_path / "already-onboarded"
    app_dir.mkdir()
    _write_scan_dir(app_dir, "2026-03-30", name="humana-com")

    messages: list[str] = []
    result = await import_app(
        db_client,
        directory=app_dir,
        org_unit_id=existing.org_unit_id,
        brand_id=existing.brand_id,
        name="Humana.com",
        on_progress=messages.append,
    )

    assert result.app_created is False
    assert result.app_id == existing.id

    resp = await db_client.get(f"/api/v1/apps/{existing.id}")
    assert resp.json()["name"] == "humana-com"

    joined = "\n".join(messages).lower()
    assert "locked" in joined or "ignor" in joined


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
    _write_scan_dir(app_dir, "2026-03-30", name="foo.com")
    _write_scan_dir(app_dir, "2026-04-01", name="bar.com")

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
    # The conflict is reported by slug — the unit that actually makes them distinct Apps.
    assert "foo-com" in message
    assert "bar-com" in message

    for slug in ("foo-com", "bar-com"):
        resp = await db_client.get(f"/api/v1/apps/slug/{slug}")
        assert resp.status_code == 404


async def test_import_warns_on_non_date_entries_and_continues(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)

    app_dir = tmp_path / "mixed"
    app_dir.mkdir()
    _write_scan_dir(app_dir, "2026-03-30", name="foo.com")

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
    existing = await make_app_with_org_unit(db_session, slug="foo-com")

    app_dir = tmp_path / "anything"
    app_dir.mkdir()
    for date in ["2026-03-30", "2026-04-01"]:
        _write_scan_dir(app_dir, date, name="foo.com")

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
    assert "foo-com" in joined

    for ingest_result in result.ingest_results:
        assert any(str(ingest_result.scan_run_id) in m for m in messages)
    for date in ("2026-03-30", "2026-04-01"):
        assert any(date in m for m in messages)


async def test_import_name_override_non_equivalent_on_existing_app_warns_and_continues(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    existing = await make_app_with_org_unit(db_session, app_name="humana-com", slug="humana-com")

    app_dir = tmp_path / "stale-override"
    app_dir.mkdir()
    _write_scan_dir(app_dir, "2026-03-30", name="humana-com")

    messages: list[str] = []
    result = await import_app(
        db_client,
        directory=app_dir,
        org_unit_id=existing.org_unit_id,
        brand_id=existing.brand_id,
        name="Totally Different",
        on_progress=messages.append,
    )

    assert result.app_created is False
    assert result.app_id == existing.id

    resp = await db_client.get(f"/api/v1/apps/{existing.id}")
    assert resp.json()["name"] == "humana-com"

    joined = "\n".join(messages).lower()
    assert "locked" in joined or "ignor" in joined


async def test_import_non_equivalent_name_creates_visible_sibling_app(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)

    resp = await db_client.post(
        "/api/v1/apps",
        json={"name": "Bar App", "brand_id": brand.id, "org_unit_id": org_unit.id},
    )
    assert resp.status_code == 201
    existing_id = resp.json()["id"]

    app_dir = tmp_path / "sibling"
    app_dir.mkdir()
    _write_scan_dir(app_dir, "2026-03-30", name="foo.com")

    result = await import_app(db_client, directory=app_dir, org_unit_id=org_unit.id, brand_id=brand.id)

    assert result.app_created is True
    assert result.app_id != existing_id

    resp = await db_client.get("/api/v1/apps")
    assert len(resp.json()["items"]) == 2


async def test_import_same_slug_variants_across_dates_create_one_app_with_newest_name(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)

    app_dir = tmp_path / "casing-drift"
    app_dir.mkdir()

    # The scan tool changed casing between runs; both names derive to foo-com.
    _write_scan_dir(app_dir, "2026-03-01", name="FOO.COM")
    _write_scan_dir(app_dir, "2026-04-01", name="foo.com")

    result = await import_app(db_client, directory=app_dir, org_unit_id=org_unit.id, brand_id=brand.id)

    assert result.app_created is True
    assert result.app_slug == "foo-com"
    assert len(result.ingest_results) == 2

    resp = await db_client.get(f"/api/v1/apps/{result.app_id}")
    app = resp.json()
    assert app["slug"] == "foo-com"
    assert app["name"] == "foo.com"  # newest scan's variant wins, not the older "FOO.COM"

    resp = await db_client.get("/api/v1/apps")
    assert len(resp.json()["items"]) == 1


async def test_import_name_override_wins_over_newest_same_slug_variant(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)

    app_dir = tmp_path / "override-vs-variants"
    app_dir.mkdir()

    _write_scan_dir(app_dir, "2026-03-01", name="FOO.COM")
    _write_scan_dir(app_dir, "2026-04-01", name="foo.com")

    result = await import_app(db_client, directory=app_dir, org_unit_id=org_unit.id, brand_id=brand.id, name="Foo.com")

    assert result.app_created is True
    resp = await db_client.get(f"/api/v1/apps/{result.app_id}")
    app = resp.json()
    assert app["name"] == "Foo.com"  # explicit override beats the newest variant "foo.com"
    assert app["slug"] == "foo-com"


async def test_import_name_deriving_to_empty_slug_fails_loudly(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)

    app_dir = tmp_path / "symbols-only"
    app_dir.mkdir()
    _write_scan_dir(app_dir, "2026-03-30", name="!!!")

    with pytest.raises(UnderivableAppNameError, match="empty slug"):
        await import_app(db_client, directory=app_dir, org_unit_id=org_unit.id, brand_id=brand.id)

    resp = await db_client.get("/api/v1/apps")
    assert resp.json()["items"] == []


async def test_import_mixed_tz_scanned_at_resolves_and_picks_newest(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)

    app_dir = tmp_path / "tz-drift"
    app_dir.mkdir()

    # The older scan carries a tz-aware endTime; the newer scan's has no offset.
    # Comparing them to pick the newest must not raise on the awareness mismatch.
    _write_scan_dir(app_dir, "2026-04-01", name="FOO.COM", end_time="2026-04-01T12:00:00Z")
    _write_scan_dir(app_dir, "2026-05-01", name="foo.com", end_time="2026-05-01T12:00:00")  # offset-less — assumed UTC

    result = await import_app(db_client, directory=app_dir, org_unit_id=org_unit.id, brand_id=brand.id)

    assert result.app_created is True
    assert result.app_slug == "foo-com"
    assert len(result.ingest_results) == 2

    resp = await db_client.get(f"/api/v1/apps/{result.app_id}")
    assert resp.json()["name"] == "foo.com"  # the offset-less newer scan wins after UTC coercion


async def test_import_missing_name_reported_even_alongside_unslugifiable_name(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)

    app_dir = tmp_path / "missing-and-unslugifiable"
    app_dir.mkdir()

    # One subdir's payload has no name; another's name is present but derives to an
    # empty slug. The unslugifiable name must not pre-empt the structured report —
    # the missing-name diagnostic has to survive rather than be lost to a raw ValueError.
    (app_dir / "2026-03-30").mkdir()
    nameless = make_axe_payload(name="foo.com", url="https://foo.com/")
    del nameless["name"]
    (app_dir / "2026-03-30" / "nameless.json").write_text(json.dumps(nameless))

    (app_dir / "2026-04-01").mkdir()
    symbols = make_axe_payload(name="!!!", url="https://foo.com/")
    (app_dir / "2026-04-01" / "symbols.json").write_text(json.dumps(symbols))

    with pytest.raises(NameResolutionError) as exc_info:
        await import_app(db_client, directory=app_dir, org_unit_id=org_unit.id, brand_id=brand.id)

    assert "nameless.json" in str(exc_info.value)


async def test_import_underivable_name_override_fails_as_operator_error(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)

    app_dir = tmp_path / "bad-override"
    app_dir.mkdir()
    _write_scan_dir(app_dir, "2026-03-30", name="foo.com")

    with pytest.raises(UnderivableAppNameError, match="empty slug"):
        await import_app(db_client, directory=app_dir, org_unit_id=org_unit.id, brand_id=brand.id, name="!!!")
