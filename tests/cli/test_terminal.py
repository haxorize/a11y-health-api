import sys
from pathlib import Path

import httpx
import pytest

from a11y_health.cli import _terminal
from a11y_health.cli._client import ApiError, make_client
from a11y_health.cli._operations import AppNotFoundError, ImportResult, IngestResult
from tests.factories import write_scan_file


def _ingest_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], directory: Path
) -> tuple[object, str]:
    # Every failure pinned below happens while reading the directory, before any
    # request — so these drive the real main() with no server behind it.
    monkeypatch.setattr(sys, "argv", ["a11y", "ingest", str(directory)])
    with pytest.raises(SystemExit) as exc_info:
        _terminal.main()
    return exc_info.value.code, capsys.readouterr().out


def test_main_no_command_exits_with_argparse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["a11y"])
    with pytest.raises(SystemExit) as exc_info:
        _terminal.main()
    assert exc_info.value.code == 2


# Reds if `_run` builds its own client again: the socket suite drives
# `make_client`, so the client `a11y` ships is only under test while `_run`
# goes through it.
def test_run_builds_the_shipped_client(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[str] = []

    def spy(base_url: str):
        built.append(base_url)
        return make_client(base_url)

    async def call(_client) -> str:
        return "ok"

    monkeypatch.setattr(_terminal, "make_client", spy)

    assert _terminal._run("http://spy", call) == "ok"
    assert built == ["http://spy"]


def test_main_ingest_dispatches_to_ingest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, Path] = {}

    async def fake_ingest(_client, *, directory, on_progress):
        captured["directory"] = directory
        return IngestResult(app_id=1, app_slug="foo", scan_run_id=2, pages_uploaded=3, errors=[])

    monkeypatch.setattr(_terminal, "ingest", fake_ingest)
    monkeypatch.setattr(sys, "argv", ["a11y", "ingest", str(tmp_path)])

    _terminal.main()

    assert captured["directory"] == tmp_path


def test_main_ingest_exits_when_uploads_fail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def fake_ingest(_client, *, directory, on_progress):
        return IngestResult(app_id=1, app_slug="foo", scan_run_id=2, pages_uploaded=0, errors=["a.json: 422 boom"])

    monkeypatch.setattr(_terminal, "ingest", fake_ingest)
    monkeypatch.setattr(sys, "argv", ["a11y", "ingest", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        _terminal.main()
    assert exc_info.value.code == 1


def test_main_import_dispatches_to_import_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    async def fake_import(_client, *, directory, org_unit_id, brand_id, name, on_progress):
        captured["directory"] = directory
        captured["org_unit_id"] = org_unit_id
        captured["brand_id"] = brand_id
        captured["name"] = name
        return ImportResult(app_id=1, app_slug="foo", app_created=True, ingest_results=[])

    monkeypatch.setattr(_terminal, "import_app", fake_import)
    monkeypatch.setattr(
        sys,
        "argv",
        ["a11y", "import", str(tmp_path), "--org-unit-id", "7", "--brand-id", "9", "--name", "Humana.com"],
    )

    _terminal.main()

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

    monkeypatch.setattr(_terminal, "import_app", fake_import)
    monkeypatch.setattr(sys, "argv", ["a11y", "import", str(tmp_path), "--org-unit-id", "1", "--brand-id", "1"])

    with pytest.raises(SystemExit) as exc_info:
        _terminal.main()
    assert exc_info.value.code == 1


def test_main_org_units_list_renders_id_name_and_parent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_list(_client):
        return [
            {"id": 1, "name": "Humana", "parent_id": None},
            {"id": 2, "name": "CenterWell", "parent_id": 1},
        ]

    monkeypatch.setattr(_terminal, "list_org_units", fake_list)
    monkeypatch.setattr(sys, "argv", ["a11y", "org-units", "list"])

    _terminal.main()

    out = capsys.readouterr().out
    assert "Humana" in out
    assert "CenterWell" in out
    assert "-" in out  # root org unit renders its absent parent as a dash


def test_main_brands_list_renders_id_and_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_list(_client):
        return [{"id": 5, "name": "Humana"}]

    monkeypatch.setattr(_terminal, "list_brands", fake_list)
    monkeypatch.setattr(sys, "argv", ["a11y", "brands", "list"])

    _terminal.main()

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

    monkeypatch.setattr(_terminal, "create_org_unit", fake_create)
    monkeypatch.setattr(sys, "argv", ["a11y", "org-units", "create", "Engineering", "--parent-id", "7"])

    _terminal.main()

    assert captured == {"name": "Engineering", "parent_id": 7}
    assert "42" in capsys.readouterr().out


def test_main_org_units_create_surfaces_coded_error_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_create(_client, *, name, parent_id):
        raise ApiError(code="not_found", message="parent 999 not found")

    monkeypatch.setattr(_terminal, "create_org_unit", fake_create)
    monkeypatch.setattr(sys, "argv", ["a11y", "org-units", "create", "Orphan", "--parent-id", "999"])

    with pytest.raises(SystemExit) as exc_info:
        _terminal.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "not_found" in out
    assert "parent 999 not found" in out


def test_main_ingest_surfaces_domain_error_as_clean_line_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # A local, operator-facing failure (here: the app isn't registered) must
    # print its guidance as a clean ERROR line and exit non-zero, not dump a
    # traceback.
    async def fake_ingest(_client, *, directory, on_progress):
        raise AppNotFoundError("unknown.com", "unknown-com")

    monkeypatch.setattr(_terminal, "ingest", fake_ingest)
    monkeypatch.setattr(sys, "argv", ["a11y", "ingest", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        _terminal.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "ERROR:" in out
    assert "a11y import" in out  # the exception's onboarding guidance reached the operator


def test_main_ingest_missing_directory_prints_error_line_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, out = _ingest_failure(monkeypatch, capsys, tmp_path / "does-not-exist")

    assert code == 1
    assert "ERROR: Directory does not exist" in out


def test_main_ingest_empty_directory_prints_error_line_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, out = _ingest_failure(monkeypatch, capsys, tmp_path)

    assert code == 1
    assert "ERROR: No JSON files found" in out


def test_main_ingest_malformed_scan_file_prints_error_line_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    (tmp_path / "truncated.json").write_text('{"name": "foo.com"')

    code, out = _ingest_failure(monkeypatch, capsys, tmp_path)

    assert code == 1
    assert "ERROR:" in out
    assert "truncated.json" in out
    assert "not valid JSON" in out


def test_main_ingest_invalid_scan_file_prints_error_line_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    write_scan_file(tmp_path, "a.json", name="foo.com", end_time="last Tuesday")

    code, out = _ingest_failure(monkeypatch, capsys, tmp_path)

    assert code == 1
    assert "ERROR:" in out
    assert "a.json" in out
    assert "schema validation" in out
    assert "endTime" in out


def test_main_ingest_underivable_app_name_prints_error_line_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    write_scan_file(tmp_path, "a.json", name="!!!")

    code, out = _ingest_failure(monkeypatch, capsys, tmp_path)

    assert code == 1
    assert "ERROR:" in out
    assert "empty slug" in out


def test_main_lets_a_bug_traceback_instead_of_printing_an_operator_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A ValueError escaping an operation is a defect, not an operator failure.
    # It must reach the developer as a traceback rather than be flattened into
    # the one-line ERROR shape that operator failures use.
    async def buggy_ingest(_client, *, directory, on_progress):
        raise ValueError("an internal invariant broke")

    monkeypatch.setattr(_terminal, "ingest", buggy_ingest)
    monkeypatch.setattr(sys, "argv", ["a11y", "ingest", str(tmp_path)])

    with pytest.raises(ValueError, match="an internal invariant broke"):
        _terminal.main()


def test_main_interrupt_exits_cleanly_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # Ctrl-C is neither an operator error nor a defect — it's the operator
    # saying stop. It gets the shell's SIGINT code and no traceback.
    async def interrupted_ingest(_client, *, directory, on_progress):
        raise KeyboardInterrupt

    monkeypatch.setattr(_terminal, "ingest", interrupted_ingest)
    monkeypatch.setattr(sys, "argv", ["a11y", "ingest", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        _terminal.main()

    assert exc_info.value.code == 130
    assert "Interrupted" in capsys.readouterr().out


def test_main_ingest_unreachable_api_prints_error_line_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # The "forgot to start the server" case, driven through the shipped client,
    # operation, and error mapping, with only the transport's send replaced:
    # it refuses the connection the way a closed port does, on any host's
    # loopback.
    async def refuse(_transport: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
    write_scan_file(tmp_path, "a.json", name="foo.com")
    monkeypatch.setattr(sys, "argv", ["a11y", "ingest", str(tmp_path), "--base-url", "http://localhost:8000"])

    with pytest.raises(SystemExit) as exc_info:
        _terminal.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "ERROR: Could not reach the API" in out
    assert "--base-url" in out


def test_main_import_missing_directory_prints_error_line_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # `import` walks the directory instead of loading it, so it needs its own
    # guard to reach the same ERROR line `ingest` gives for the identical typo.
    monkeypatch.setattr(
        sys,
        "argv",
        ["a11y", "import", str(tmp_path / "typo"), "--org-unit-id", "1", "--brand-id", "1"],
    )

    with pytest.raises(SystemExit) as exc_info:
        _terminal.main()

    assert exc_info.value.code == 1
    assert "ERROR: Directory does not exist" in capsys.readouterr().out
