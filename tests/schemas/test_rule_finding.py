import pytest
from pydantic import ValidationError

from a11y_health.schemas.rule_finding import NodeChecks


# Strict on purpose: ingest always stores all three groups, so a row missing one
# was written past it and fails the read rather than serving as empty.
@pytest.mark.parametrize("group", ["any", "all", "none"])
def test_node_checks_refuses_a_row_missing_a_group(group: str) -> None:
    stored = {"any": [], "all": [], "none": []}
    del stored[group]

    with pytest.raises(ValidationError) as exc_info:
        NodeChecks.model_validate(stored)
    [err] = exc_info.value.errors()
    assert (err["loc"], err["type"]) == ((group,), "missing")


def test_node_checks_refuses_a_null_group() -> None:
    with pytest.raises(ValidationError) as exc_info:
        NodeChecks.model_validate({"any": None, "all": [], "none": []})
    [err] = exc_info.value.errors()
    assert (err["loc"], err["type"]) == (("any",), "list_type")
