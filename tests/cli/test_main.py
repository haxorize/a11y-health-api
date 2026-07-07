import sys
from pathlib import Path

import pytest

from a11y_health import cli
from a11y_health.cli import ApiError, ImportResult, IngestResult


def test_main_no_command_exits_with_argparse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["a11y"])
    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 2


def test_main_ingest_dispatches_to_ingest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, Path] = {}

    async def fake_ingest(_client, *, directory, on_progress):
        captured["directory"] = directory
        return IngestResult(app_id=1, app_slug="foo", scan_run_id=2, pages_uploaded=3, errors=[])

    monkeypatch.setattr(cli, "ingest", fake_ingest)
    monkeypatch.setattr(sys, "argv", ["a11y", "ingest", str(tmp_path)])

    cli.main()

    assert captured["directory"] == tmp_path


def test_main_ingest_exits_when_uploads_fail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def fake_ingest(_client, *, directory, on_progress):
        return IngestResult(app_id=1, app_slug="foo", scan_run_id=2, pages_uploaded=0, errors=["a.json: 422 boom"])

    monkeypatch.setattr(cli, "ingest", fake_ingest)
    monkeypatch.setattr(sys, "argv", ["a11y", "ingest", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 1


def test_main_import_dispatches_to_import_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    async def fake_import(_client, *, directory, org_unit_id, brand_id, name, on_progress):
        captured["directory"] = directory
        captured["org_unit_id"] = org_unit_id
        captured["brand_id"] = brand_id
        captured["name"] = name
        return ImportResult(app_id=1, app_slug="foo", app_created=True, ingest_results=[])

    monkeypatch.setattr(cli, "import_app", fake_import)
    monkeypatch.setattr(
        sys,
        "argv",
        ["a11y", "import", str(tmp_path), "--org-unit-id", "7", "--brand-id", "9", "--name", "Humana.com"],
    )

    cli.main()

    assert captured == {"directory": tmp_path, "org_unit_id": 7, "brand_id": 9, "name": "Humana.com"}


def test_main_import_exits_when_any_scan_has_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def fake_import(_client, *, directory, org_unit_id, brand_id, name, on_progress):
        return ImportResult(
            app_id=1,
            app_slug="foo",
            app_created=False,
            ingest_results=[
                IngestResult(app_id=1, app_slug="foo", scan_run_id=2, pages_uploaded=0, errors=["a.json: 422 boom"]),
            ],
        )

    monkeypatch.setattr(cli, "import_app", fake_import)
    monkeypatch.setattr(sys, "argv", ["a11y", "import", str(tmp_path), "--org-unit-id", "1", "--brand-id", "1"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 1


def test_main_org_units_list_renders_id_name_and_parent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_list(_client):
        return [
            {"id": 1, "name": "Humana", "parent_id": None},
            {"id": 2, "name": "CenterWell", "parent_id": 1},
        ]

    monkeypatch.setattr(cli, "list_org_units", fake_list)
    monkeypatch.setattr(sys, "argv", ["a11y", "org-units", "list"])

    cli.main()

    out = capsys.readouterr().out
    assert "Humana" in out
    assert "CenterWell" in out
    assert "-" in out  # root org unit renders its absent parent as a dash


def test_main_brands_list_renders_id_and_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_list(_client):
        return [{"id": 5, "name": "Humana"}]

    monkeypatch.setattr(cli, "list_brands", fake_list)
    monkeypatch.setattr(sys, "argv", ["a11y", "brands", "list"])

    cli.main()

    out = capsys.readouterr().out
    assert "Humana" in out
    assert "5" in out


def test_main_org_units_create_dispatches_and_prints_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, object] = {}

    async def fake_create(_client, *, name, parent_id):
        captured["name"] = name
        captured["parent_id"] = parent_id
        return 42

    monkeypatch.setattr(cli, "create_org_unit", fake_create)
    monkeypatch.setattr(sys, "argv", ["a11y", "org-units", "create", "Engineering", "--parent-id", "7"])

    cli.main()

    assert captured == {"name": "Engineering", "parent_id": 7}
    assert "42" in capsys.readouterr().out


def test_main_org_units_create_surfaces_coded_error_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_create(_client, *, name, parent_id):
        raise ApiError(code="not_found", message="parent 999 not found")

    monkeypatch.setattr(cli, "create_org_unit", fake_create)
    monkeypatch.setattr(sys, "argv", ["a11y", "org-units", "create", "Orphan", "--parent-id", "999"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "not_found" in out
    assert "parent 999 not found" in out
