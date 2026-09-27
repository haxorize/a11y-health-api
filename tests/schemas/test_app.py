import pytest
from pydantic import ValidationError

from a11y_health.core.slug import NAME_MAX_LENGTH
from a11y_health.schemas.app import AppCreate


def test_app_create_name_admits_the_bound_and_refuses_one_past_it() -> None:
    # Red when the constant moves and the field does not.
    AppCreate(name="a" * NAME_MAX_LENGTH, brand_id=1, org_unit_id=1)

    with pytest.raises(ValidationError, match="at most"):
        AppCreate(name="a" * (NAME_MAX_LENGTH + 1), brand_id=1, org_unit_id=1)


def test_app_create_rejects_name_deriving_to_empty_slug() -> None:
    with pytest.raises(ValidationError, match="empty"):
        AppCreate(name="!!! ($%) !!!", brand_id=1, org_unit_id=1)


def test_app_create_rejects_fully_non_latin_name() -> None:
    with pytest.raises(ValidationError, match="empty"):
        AppCreate(name="日本語", brand_id=1, org_unit_id=1)


def test_app_create_rejects_name_deriving_past_slug_length() -> None:
    # NFKD folds each "ﬃ" to "ffi", so the name passes its own 255 limit
    # while the derived slug does not
    with pytest.raises(ValidationError, match="longer than 255"):
        AppCreate(name="ﬃ" * 100, brand_id=1, org_unit_id=1)
