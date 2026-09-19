import pytest
from pydantic import ValidationError

from a11y_health.config import Settings
from a11y_health.main import create_app


def test_wildcard_origin_rejected_when_debug_false() -> None:
    with pytest.raises(ValidationError, match="Wildcard"):
        Settings(DEBUG=False, ALLOWED_ORIGINS=["*"])


def test_wildcard_origin_allowed_when_debug_true() -> None:
    settings = Settings(DEBUG=True, ALLOWED_ORIGINS=["*"])

    assert settings.ALLOWED_ORIGINS == ["*"]


def test_the_app_is_built_from_the_settings_handed_in() -> None:
    # Every one of these reaches openapi.json, which is a committed artifact
    # compared byte for byte by `make openapi-check`. The prefix is the one
    # worth a test of its own: it lands in the path of every operation rather
    # than in one info field, and it is read by the v1 router, so an app
    # factory that took settings while importing a module-level router built
    # from the process's own would pass every other assertion here.
    settings = Settings(PROJECT_NAME="Handed In", VERSION="9.9.9", API_V1_PREFIX="/api/v99")
    spec = create_app(settings).openapi()

    assert spec["info"]["title"] == "Handed In"
    assert spec["info"]["version"] == "9.9.9"
    assert spec["paths"], "the app declared no paths, so the prefix assertion below is vacuous"
    misprefixed = [path for path in spec["paths"] if not path.startswith("/api/v99")]
    assert not misprefixed, f"paths outside the prefix the settings declared: {misprefixed}"
