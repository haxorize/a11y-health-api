# Mocking

Detail moved out of `SKILL.md` when its body reached the 15,000-byte cap. Open this before mocking anything: which tool, which seam, and the async form.

Use the `mocker` fixture from `pytest-mock` rather than raw `unittest.mock` — it auto-cleans patches per test.

`monkeypatch` is the other sanctioned tool, for a plain attribute or env swap that asserts nothing about calls (a sessionmaker rebinding, `sys.argv`); reach for `mocker` when the test asserts on the call. A session-scoped fixture cannot take either — both are function-scoped — and the way around that is in [references/cli-and-migration-tests.md](references/cli-and-migration-tests.md).

```python
async def test_cli_uploads_scan(mocker) -> None:
    post = mocker.patch("httpx.AsyncClient.post", new_callable=mocker.AsyncMock)
    post.return_value.status_code = 201
    await run_ingest(...)
    post.assert_awaited_once()
```

- Mock at the seam closest to the boundary, not deep into your own code. For anything leaving the process, that seam is the transport: hand `httpx.MockTransport(handler)` to the client under test, the way `tests/cli/test_client.py` does, and the handler decodes a real request and returns a real response — so the code's own error decode, redirect, and timeout paths run rather than being stubbed past. Patch `httpx.AsyncClient.post` instead only when the assertion is about the call itself
- For async callables use `new_callable=mocker.AsyncMock` and assert with `assert_awaited_once`/`assert_awaited_with`
- Don't mock the database — the `db_session` rollback fixture is the canonical isolation mechanism
