# The mirrored test directories

The directories under `tests/` that mirror `src/a11y_health/`. The root-level files, which do not mirror anything, are listed in the skill body's § Test layout.

```
tests/
  api/
    test_health.py          # tests for api/v1/endpoints/health.py
    test_deps.py            # api/deps.py's session scope
    test_<router>.py        # one file per router, not per endpoint module — scan_runs.py declares
                            # three. Its two scan-run routers share test_scan_runs.py; pages_router
                            # is test_pages.py; a nested read takes its own file
                            # (test_scan_run_pages.py, test_scan_run_summary.py)
    test_rollup_deadlock.py # the #104 deadlock 409 through the full request stack; `integration`
  services/
    test_<resource>.py      # direct service-layer tests, one per public services/ module. The
                            # underscore-prefixed ones (_latest_snapshot, _org_subtree) have no
                            # file: they are exercised through the module that consumes them
    test_finding_persistence.py   # what one Axe Payload leaves behind across the finding tables
    test_rollup_serialization.py  # per-Owner Rollup on two sessions (#101, ADR 0029); `integration`
    test_org_unit_reparent_race.py  # reparent serialization on two sessions (#176, ADR 0047); `integration`
    test_org_unit_delete_race.py    # writes naming an Org Unit deleted underneath them (#178, ADR 0048); `integration`
    test_scan_run_race.py           # the Scan Run row lock: completion, Page Result creation, delete (#178, ADR 0048); `integration`
    test_update_race.py             # App and Org Unit updates that lock their row at the load (ADR 0048); `integration`
  schemas/
    test_<schema>.py        # Pydantic schema validation tests
  models/
    test_<model>.py         # model-level tests (defaults, constraints as declared)
  core/
    test_<module>.py        # one per core module that has one. error_body.py and exceptions.py
                            # have none — both are reached only through consumers, error_body
                            # through test_error_contract.py and cli/test_client.py's error decode
  cli/
    conftest.py             # CLI-only fixtures (no_server, live_server, socket_client, forwarded) — see cli-and-migration-tests.md
    test_<command>.py       # one file per command (test_ingest.py, test_import.py, test_org_units.py,
                            # test_brands.py)
    test_client.py          # transport, error decode, and timeouts over httpx.MockTransport
    test_live_server.py     # the CLI over a real socket (production AsyncHTTPTransport)
    test_terminal.py        # argv dispatch and the operator-facing ERROR line + exit code
  migrations/
    harness.py, roundtrip.py # the migration-body harness; the roundtrip
    test_downgrade_floor.py # the floor is a real revision and never the head; reads the Makefile
    test_<revision>.py      # migration bodies through harness.py — see cli-and-migration-tests.md
```
