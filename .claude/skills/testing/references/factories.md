# Test factories

Open this before adding or changing a helper in `tests/factories.py`. A test that only *calls* existing helpers needs their signatures in `tests/factories.py` instead — this file is about writing the helper.

Everything here is arrange-side. What a test asserts is the other half of the rule, and `SKILL.md` ("Arrange with a factory, compute the expectation yourself") owns it: a factory may reuse a production helper freely, an assertion may not.

## Naming and shape

Use simple async helper functions with explicit keyword arguments and defaults:

```python
async def make_org_unit(db: AsyncSession, *, name: str = "Test Org", parent_id: int | None = None) -> OrgUnit:
    org_unit = OrgUnit(name=name, parent_id=parent_id)
    db.add(org_unit)
    await db.flush()
    return org_unit
```

Call in tests: `org_unit = await make_org_unit(db_session, name="Humana")`

## Parent chains

For resources with required parent FK chains, add `make_<resource>_with_parents` composite helpers that create the full ancestry in one call:

```python
scan_run = await make_scan_run_with_parents(db_session, slug="my-app", status=ScanRunStatus.PENDING)
```

## In-memory Axe Payloads

For building in-memory data structures (an Axe Payload and the violations inside it), use sync helpers that return plain dicts:

```python
def make_violation(rule_id: str, impact: str, *, tags: list[str] | None = None) -> dict[str, Any]:
    return {"id": rule_id, "impact": impact, ...}

def make_axe_payload(
    *,
    name: str = "test-app",
    url: str = "https://example.com",
    violations: Any = None,
    incomplete: Any = None,
    end_time: Any = None,
    unmodeled: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`end_time` is untyped because several tests hand the boundary values it
    must reject; `None` leaves the key out. `unmodeled` is for keys the schema
    does not model, which the stored Raw JSON must still carry — merged first,
    so it can never shadow a named argument."""
    ...
    return {**(unmodeled or {}), **payload}
```

These don't touch the DB and don't need `async` or `flush()`.

## Sequenced defaults

For factories that create many instances of the same resource, use a module-level `itertools.count()` sequence to generate unique defaults automatically:

```python
_brand_seq = itertools.count(1)


async def make_brand(db: AsyncSession, *, name: str | None = None) -> Brand:
    if name is None:
        name = f"Test Brand {next(_brand_seq)}"
    ...
```

## The shared arrange helpers

Two arrange helpers own the "ingest these Axe Payloads, complete the run" core every scoring and orchestration test shares: `ingest_pages_and_complete`, and `ingest_and_score` on top of it, with `complete_new_scan_run` and `score_new_scan_run` making the run first. They are arrange only: the shared factory never owns a subject, so what a test invokes after arrange completes (the orchestration handler, a rollup call) stays visible at the test's own call site. `ingest_and_score`'s final call is the act only for a test whose subject is the score compute itself; a rollup test uses it to arrange an already-scored App. A new scoring or rollup tail is a new helper name, never a mode flag on an existing one.

`DEFAULT_SCORE_AGGREGATES` and `DEFAULT_SNAPSHOT_AT` are the one home of the snapshot defaults — the Score Aggregates and the Observation Time: `build_score_snapshot` (not persisted) and `make_score_snapshot` (persisted) both read their keyword defaults off them, and a test that has to build a raw `ScoreSnapshot` row (one `owned()` cannot express) spreads `DEFAULT_SCORE_AGGREGATES._asdict()` in beside `snapshot_at=DEFAULT_SNAPSHOT_AT` rather than restating the values.

## Query helpers

For test assertions that query derived state (e.g., checking rollup snapshots), add query helpers to `factories.py`. The snapshot readers share one ordering, Latest Score Snapshot's (observation time, ties to the higher id), and each `latest_*` reader is built as the last element of its owner's list, so the two cannot disagree by construction; `tests/test_factories.py` pins the ordering itself (the latest is the newest observation, and a tie goes to the higher id), not the agreement. Read an owner's snapshots through these rather than an inline `select(ScoreSnapshot)`:

```python
async def latest_ou_snapshot(db: AsyncSession, org_unit_id: int) -> ScoreSnapshot:
    return (await ou_snapshots(db, org_unit_id))[-1]
```
