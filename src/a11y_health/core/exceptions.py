import enum


class NotFoundError(Exception):
    def __init__(self, resource: str, resource_id: object) -> None:
        self.resource = resource
        self.resource_id = resource_id
        super().__init__(f"{resource} {resource_id} not found")


class CircularReferenceError(Exception):
    def __init__(self, resource: str, resource_id: object, parent_id: object) -> None:
        self.resource = resource
        self.resource_id = resource_id
        self.parent_id = parent_id
        super().__init__(f"{resource} {resource_id} cannot have {parent_id} as parent: circular reference")


class DuplicateSlugError(Exception):
    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"App with slug '{slug}' already exists")


class InvalidStatusTransitionError(Exception):
    def __init__(self, resource: str, resource_id: object, current_status: enum.Enum, target_status: enum.Enum) -> None:
        self.resource = resource
        self.resource_id = resource_id
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(
            f"{resource} {resource_id} cannot transition from {current_status.value} to {target_status.value}"
        )


class ScanRunCompletedError(Exception):
    def __init__(self, scan_run_id: object) -> None:
        self.scan_run_id = scan_run_id
        super().__init__(f"Scan run {scan_run_id} is completed and cannot accept new pages")


class HasDependentsError(Exception):
    def __init__(self, resource: str, resource_id: object) -> None:
        self.resource = resource
        self.resource_id = resource_id
        super().__init__(f"Cannot delete {resource} {resource_id}: it has dependent records")
