import enum
from collections.abc import Mapping
from types import MappingProxyType
from typing import TypeVar

from a11y_health.models.app import App
from a11y_health.models.brand import Brand
from a11y_health.models.org_unit import OrgUnit
from a11y_health.models.rule_finding import RuleFinding
from a11y_health.models.scan_run import ScanRun
from a11y_health.models.score_snapshot import ScoreSnapshot

# The models ENTITY_LABELS names, so an unlabeled model fails the type check
# rather than raising KeyError while its error is being built.
type LabeledModel = type[App] | type[Brand] | type[OrgUnit] | type[ScanRun] | type[RuleFinding] | type[ScoreSnapshot]
Labeled = TypeVar("Labeled", bound=App | Brand | OrgUnit | ScanRun | RuleFinding | ScoreSnapshot)

# How a mode taking a model type names its entity, so an entity reads
# identically across all its errors. The three modes serving one entity
# (DuplicateSlugError, ScanRunCompletedError, EmptyScanRunError) open on its
# label as a literal instead, so each stays searchable from its first word
# (#162). ScoreSnapshot is only ever guarded as a Scan Run's summary
# lookup, so that is its canonical label. Read-only so the table stays closed
# at runtime, not just by convention.
ENTITY_LABELS: Mapping[type, str] = MappingProxyType(
    {
        App: "App",
        Brand: "Brand",
        OrgUnit: "Org unit",
        ScanRun: "Scan run",
        RuleFinding: "Finding",
        ScoreSnapshot: "Scan run summary",
    }
)


class DomainError(Exception):
    """Base for every domain error mode. Subclassing is what makes an error a
    mode: the error contract's handler catches `DomainError`, and its
    exhaustiveness test requires a table entry for every subclass."""


class NotFoundError(DomainError):
    def __init__(self, entity: LabeledModel, resource_id: object) -> None:
        self.resource = resource = ENTITY_LABELS[entity]
        self.resource_id = resource_id
        super().__init__(f"{resource} {resource_id} not found")


class CircularReferenceError(DomainError):
    def __init__(self, entity: LabeledModel, resource_id: object, parent_id: object) -> None:
        self.resource = resource = ENTITY_LABELS[entity]
        self.resource_id = resource_id
        self.parent_id = parent_id
        super().__init__(f"{resource} {resource_id} cannot have {parent_id} as parent: circular reference")


class DuplicateRootError(DomainError):
    def __init__(self, entity: LabeledModel, existing_root_id: object | None = None) -> None:
        self.resource = resource = ENTITY_LABELS[entity]
        self.existing_root_id = existing_root_id
        # existing_root_id is None on the race path: the root race guard
        # builds this instance before its flush, so the winner is never
        # looked up.
        if existing_root_id is None:
            message = f"A top-level {resource.lower()} already exists: only one is allowed"
        else:
            message = f"{resource} {existing_root_id} is already the top-level {resource.lower()}: only one is allowed"
        super().__init__(message)


class DuplicateSlugError(DomainError):
    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"App with slug '{slug}' already exists")


class InvalidStatusTransitionError(DomainError):
    def __init__(
        self, entity: LabeledModel, resource_id: object, current_status: enum.Enum, target_status: enum.Enum
    ) -> None:
        self.resource = resource = ENTITY_LABELS[entity]
        self.resource_id = resource_id
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(
            f"{resource} {resource_id} cannot transition from {current_status.value} to {target_status.value}"
        )


class ScanRunCompletedError(DomainError):
    def __init__(self, scan_run_id: object) -> None:
        self.scan_run_id = scan_run_id
        super().__init__(f"Scan run {scan_run_id} is completed and cannot accept new pages")


class EmptyScanRunError(DomainError):
    def __init__(self, scan_run_id: object) -> None:
        self.scan_run_id = scan_run_id
        super().__init__(f"Scan run {scan_run_id} has no page results and cannot be completed")


class InvalidAxePayloadError(DomainError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Invalid axe payload: {reason}")


class ConcurrentRollupError(DomainError):
    def __init__(self, entity: LabeledModel, resource_id: object) -> None:
        self.resource = resource = ENTITY_LABELS[entity]
        self.resource_id = resource_id
        super().__init__(
            f"{resource} {resource_id} score was updated by another request at the same time; retry the request"
        )


class HasDependentsError(DomainError):
    def __init__(self, entity: LabeledModel, resource_id: object) -> None:
        self.resource = resource = ENTITY_LABELS[entity]
        self.resource_id = resource_id
        super().__init__(f"Cannot delete {resource} {resource_id}: it has dependent records")
