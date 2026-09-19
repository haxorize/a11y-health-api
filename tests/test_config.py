import pytest
from pydantic import ValidationError

from a11y_health.config import Settings


def test_wildcard_origin_rejected_when_debug_false() -> None:
    with pytest.raises(ValidationError, match="Wildcard"):
        Settings(DEBUG=False, ALLOWED_ORIGINS=["*"])


def test_wildcard_origin_allowed_when_debug_true() -> None:
    settings = Settings(DEBUG=True, ALLOWED_ORIGINS=["*"])

    assert settings.ALLOWED_ORIGINS == ["*"]
