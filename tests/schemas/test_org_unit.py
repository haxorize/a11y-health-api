import pytest
from pydantic import ValidationError

from a11y_health.core.slug import NAME_MAX_LENGTH
from a11y_health.schemas.org_unit import OrgUnitCreate, OrgUnitUpdate


@pytest.mark.parametrize("schema", [OrgUnitCreate, OrgUnitUpdate])
def test_the_name_admits_the_bound_and_refuses_one_past_it(schema: type[OrgUnitCreate] | type[OrgUnitUpdate]) -> None:
    # Red when the constant moves and the field does not.
    schema(name="a" * NAME_MAX_LENGTH)

    with pytest.raises(ValidationError) as exc_info:
        schema(name="a" * (NAME_MAX_LENGTH + 1))
    [err] = exc_info.value.errors()
    assert (err["loc"], err["type"]) == (("name",), "string_too_long")
