# Per-owner variation concentrates in one Owner Dispatcher module

The Owner concept was held in four representations that didn't know about each
other: the `OWNER_ID_COLUMNS` enum→column map living in the model layer, the
partial `_ROLLUP_OWNERS` dict (runtime-`KeyError` exhaustiveness), three
hand-written per-owner history listers, and stringly
`**{column.key: owner_id}` snapshot construction pinned only by a canary test —
plus twin rollup entrypoints, twin children queries, and the brand-membership
predicate spelled twice. A fourth owner type would touch three modules, and the
history-lister path would fail silently. We concentrate all of it in
`services/owner.py` — the **Owner Dispatcher** (DOMAIN.md): an owner spec table
derived from a single exhaustive `assert_never` match over
`ScoreSnapshotOwnerType` (one exhaustiveness mechanism, at typecheck level),
consumed by scope resolution, the latest/history score reads, and the rollup
machinery, all in the same module.

```python
@dataclass(frozen=True)
class RollupSpec:
    unique_index: str                    # the #98 race backstop this owner defends
    children: ChildrenRead               # (session, owner_id) -> latest child snapshots
    cascade_parent: ParentLookup | None  # ORG_UNIT's parent cascade; BRAND None

@dataclass(frozen=True)
class OwnerSpec:
    owner_type: ScoreSnapshotOwnerType
    id_column: InstrumentedAttribute[int | None]      # ScoreSnapshot.<owner>_id
    entity: type[App] | type[OrgUnit] | type[Brand]   # existence guard + label
    rollup: RollupSpec | None            # None: APP snapshots come from scoring

OWNERS: Mapping[ScoreSnapshotOwnerType, OwnerSpec]   # MappingProxyType over
                                                     # {t: _spec_for(t) for t in enum}

async def list_scores(session, owner_type, owner_id, *,
                      cursor=None, limit=DEFAULT_PAGE_SIZE, descending=False)
async def rollup(session, owner_type, owner_id)      # ValueError on APP; cascades
def owned(owner_type, owner_id, *, scan_run_id=None, **aggregates) -> ScoreSnapshot
def brand_apps(brand_id) -> Select                   # the one membership predicate
```

**The read/write split is redrawn as computation-vs-dispatch.** `score.py`
(the read side) is absorbed into the dispatcher; `score_snapshot.py` keeps
app-score computation. This was the real trade-off: a data-only spec table
(behavior staying in the old read/write homes) preserved the familiar split
with the smallest diff but left owner variation spanning two modules, and a
specs-plus-rollups middle ground made a third scoring module — both rejected
because adding an owner type should touch exactly one module. Per-owner
subclasses were rejected because each concern smears across three class bodies
and exhaustiveness degrades to subclass discipline; growing the existing
generic helpers with more parameters is the shallow shape polished, not
deepened.

**`owned()` replaces `build_snapshot`.** Picking the owner column via the spec
makes exactly-one-owner structural, so `_require_exactly_one_owner` and its
`ValueError` paths are deleted (the database check constraint stays as the
backstop); `scan_run_id` stays guarded to APP.

**The sanctioned test seam is the `OWNERS` module attribute.** The rollup-race
harness swaps the whole table —
`mocker.patch.object(owner, "OWNERS", MappingProxyType({**OWNERS, ...}))` with
a `dataclasses.replace`d spec — and `rollup()` resolves it at call time. The
test-side `ReadChildren` Protocol and the kwargs canary are deleted; the
production types make both redundant. `patch.dict` was rejected because
`MappingProxyType` refuses `__setitem__` and dropping the proxy loses
import-time immutability; an injectable children parameter was rejected as a
test-only surface on the production interface.

Unchanged by design: the scope semantics of
[ADR 0034](0034-under-org-unit-scope-resolves-per-owner-type.md),
[ADR 0035](0035-direct-only-opt-in-refines-the-under-org-unit-scope.md), and
[ADR 0036](0036-brand-scope-resolves-per-owner-type.md) relocate verbatim; the
[ADR 0029](0029-per-owner-advisory-lock-rollup-serialization.md)
lock stays the rollup's first statement with a byte-stable key string; keysets
(and so in-flight cursors) don't move; the wire contract is untouched.
Sequencing guard: the first slice introduces the specs and re-points the
serialization harness at the `OWNERS` seam while production still runs the old
paths, proven under repeated runs before any behavior moves. The module's
charter is closed (DOMAIN.md "Owner Dispatcher"): app-score computation stays
out, and no per-owner dispatch may exist anywhere else.
