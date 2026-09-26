import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from a11y_health.config import Settings


def test_wildcard_origin_rejected_when_debug_false() -> None:
    with pytest.raises(ValidationError, match="Wildcard"):
        Settings(DEBUG=False, ALLOWED_ORIGINS=["*"])


def test_wildcard_origin_allowed_when_debug_true() -> None:
    settings = Settings(DEBUG=True, ALLOWED_ORIGINS=["*"])

    assert settings.ALLOWED_ORIGINS == ["*"]


_REPO = Path(__file__).resolve().parent.parent
_README_ROW = re.compile(r"^\| `([A-Z_]+)` \| `([^`]*)` \|", re.MULTILINE)
_EXAMPLE_NAME = re.compile(r"^# ([A-Z_]+)=$", re.MULTILINE)


@pytest.fixture
def no_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.usefixtures("no_environment")
def test_the_readme_defaults_are_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # Each documented default, read the way the operator's environment variable
    # would be, is what Settings holds with neither a .env nor the variable.
    documented = dict(_README_ROW.findall((_REPO / "README.md").read_text()))
    assert documented.keys() == Settings.model_fields.keys()
    defaults = Settings(_env_file=None)

    for name, value in documented.items():
        monkeypatch.setenv(name, value)
    documented_settings = Settings(_env_file=None)

    assert documented_settings.model_dump() == defaults.model_dump()


def test_the_example_file_lists_every_setting_and_nothing_else() -> None:
    # A name spelled differently in .env.example goes unread, and the field
    # silently keeps its default (the comment above `Settings`).
    listed = _EXAMPLE_NAME.findall((_REPO / ".env.example").read_text())

    assert sorted(listed) == sorted(Settings.model_fields)
