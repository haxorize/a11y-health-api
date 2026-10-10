# Domain exceptions

Exception classes subclass `DomainError` and store context as instance attributes before calling `super().__init__()`. `HasDependentsError` is the shape, quoted as it stands in `core/exceptions.py`: it takes the model type, resolves the label from `ENTITY_LABELS`, and opens its message on a literal:
```python
class HasDependentsError(DomainError):
    def __init__(self, entity: LabeledModel, resource_id: object) -> None:
        self.resource = resource = ENTITY_LABELS[entity]
        self.resource_id = resource_id
        super().__init__(f"Cannot delete {resource} {resource_id}: it has dependent records")
```

Follow this pattern for new exceptions — attributes enable structured logging and testing; `str(exc)` provides the HTTP response detail.

**Open a new message on a literal rather than on an interpolated value** — a message pasted from a log or a bug report has to grep back to the one line that raises it, and a leading `{resource}` leaves only the tail to search for. This is a rule for messages not yet written: five of the ten current subclasses open interpolated, `NotFoundError` among them. Their text is the served body — `core/error_contract.py` sends `str(exc)` — so rewording one moves `openapi.json`, the UI's generated client, and the tests that pin the exact string (in `tests/core/test_error_contract.py` and `tests/core/test_existence.py`). #184 owns that sweep; until it lands, **when rewording an existing message** match the file rather than the rule — a message written new follows the rule.
