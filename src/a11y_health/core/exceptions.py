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
