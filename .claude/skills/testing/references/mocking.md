# Mocking

Open this before mocking anything: which tool, which seam, and the async form.

Use the `mocker` fixture from `pytest-mock` rather than raw `unittest.mock` — it auto-cleans patches per test.

`monkeypatch` is the other sanctioned tool, for a plain attribute or env swap that asserts nothing about calls (an environment variable, `sys.argv`); reach for `mocker` when the test asserts on the call. A session-scoped fixture cannot take either — both are function-scoped — and the way around that is in [cli-and-migration-tests.md](cli-and-migration-tests.md).

```python
async def test_complete_scan_run_sends_the_status(mocker) -> None:
    request = mocker.patch.object(httpx.AsyncClient, "request", new_callable=mocker.AsyncMock)
    request.return_value = httpx.Response(200)
    async with httpx.AsyncClient(base_url="http://test") as client:
        await complete_scan_run(client, scan_run_id=7)
    request.assert_awaited_once_with("PATCH", "/api/v1/scan-runs/7", json={"status": "completed"})
```

- Mock at the seam closest to the boundary, not deep into your own code. For anything leaving the process, that seam is the transport: hand `httpx.MockTransport(handler)` to the client under test, the way `tests/cli/test_client.py` does, and the handler decodes a real request and returns a real response — so the code's own error decode, redirect, and timeout paths run rather than being stubbed past. Patch `httpx.AsyncClient.request` instead, as above, only when the assertion is about the call itself: every request the CLI makes goes through it (`_send` in `src/a11y_health/cli/_client.py`), so a patch on `post` or `get` never fires
- For async callables use `new_callable=mocker.AsyncMock` and assert with `assert_awaited_once`/`assert_awaited_with`
- Don't mock the database — the `db_session` rollback fixture is the canonical isolation mechanism
