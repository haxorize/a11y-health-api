import pytest
from pydantic import ValidationError

from a11y_health.schemas.app import AppCreate, AppUpdate


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


def test_app_update_carries_no_identity_fields() -> None:
    assert set(AppUpdate.model_fields) == {"org_unit_id"}
