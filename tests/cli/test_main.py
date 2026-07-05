import sys
from pathlib import Path

import pytest

from a11y_health import cli
from a11y_health.cli import ImportResult, IngestResult


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
