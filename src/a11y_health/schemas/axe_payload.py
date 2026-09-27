"""The validated boundary for axe DevTools JSON — the axe boundary.

All validation of an Axe Payload — structural and semantic (impact values,
classification shape, WCAG criteria parsing, the identity fields `name` and
`endTime`) — happens here, and `parse_axe_payload` is the one crossing. Two
callers make it: the page-result ingest service, as its first statement, so
the endpoint hands the raw body straight through and the service owns the
`invalid_axe_payload` error mode; and the CLI at scan load, so a file the
server would reject fails before any upload. Below the crossing only the typed
`AxePayload` exists.

See `docs/architecture.md` ("The layers") and
`docs/adr/0009-axe-payload-pydantic-boundary.md`.
"""

import re
from datetime import UTC, datetime
from typing import Any, NamedTuple, Self

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, field_validator, model_validator

from a11y_health.core.exceptions import InvalidAxePayloadError
from a11y_health.models.classification import Classification, classifications_in
from a11y_health.models.enums import Category, Impact


class AxeNode(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    html: str
    target: list[str]
    impact: Impact
    failure_summary: str | None = Field(default=None, alias="failureSummary")
    any: list[dict[str, Any]] = Field(default_factory=list)
    all: list[dict[str, Any]] = Field(default_factory=list)
    none: list[dict[str, Any]] = Field(default_factory=list)


class _RuleTags(NamedTuple):
    category: Category
    wcag_criteria: list[str]
    classifications: list[Classification]


_WCAG_CRITERION = re.compile(r"^wcag(\d)(\d)(\d+)$")
_CATEGORY_TAG = re.compile(r"^cat\.(.+)$")
_CATEGORIES = {c.value: c for c in Category}
_WEB_ADDRESS = re.compile(r"^https?://", re.IGNORECASE)


def _read_rule_tags(tags: list[str]) -> _RuleTags:
    """A rule's Category, WCAG Criteria, and Classifications, all read from its
    tags. Unknown WCAG-shaped tags are dropped, since the axe tag set is open;
    the category tag is the exception, and a rule with none, or with one that
    is not a known Category, raises `ValueError`, which `parse_axe_payload`
    reports as the 400 `invalid_axe_payload`."""
    categories = (m.group(1) for tag in tags if (m := _CATEGORY_TAG.match(tag)))
    value = next(categories, None)
    if value is None:
        raise ValueError("No category tag found")
    if value not in _CATEGORIES:
        raise ValueError(f"Unknown category: {value}")
    criteria = [".".join(m.groups()) for tag in tags if (m := _WCAG_CRITERION.match(tag))]
    return _RuleTags(_CATEGORIES[value], criteria, classifications_in(tags))


class AxeRule(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    impact: Impact
    description: str
    help: str
    help_url: str = Field(alias="helpUrl")
    tags: list[str]
    nodes: list[AxeNode]
    _read: _RuleTags = PrivateAttr()

    @field_validator("help_url")
    @classmethod
    def require_web_address(cls, value: str) -> str:
        # Stored and served verbatim, so a `javascript:` link accepted here
        # reaches every client that renders one. Empty is no link at all.
        if value and not _WEB_ADDRESS.match(value):
            raise ValueError("must be an http or https address")
        return value

    @model_validator(mode="after")
    def read_tags(self) -> Self:
        self._read = _read_rule_tags(self.tags)
        return self

    @property
    def category(self) -> Category:
        return self._read.category

    @property
    def wcag_criteria(self) -> list[str]:
        return self._read.wcag_criteria

    @property
    def classifications(self) -> list[Classification]:
        return self._read.classifications


class AxeFindings(BaseModel):
    violations: list[AxeRule]
    incomplete: list[AxeRule]
    passes: list[Any] = Field(default_factory=list)
    inapplicable: list[Any] = Field(default_factory=list)


class AxeTestSubject(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    file_name: str = Field(min_length=1, alias="fileName")


class AxePayload(BaseModel):
    # No `populate_by_name`: the root accepts the axe spellings only, so a
    # snake_case `end_time` or `test_subject` key is an unmodeled key like any
    # other, not a second spelling that can fail the load.

    # Declared first because pydantic reports errors in declaration order: a
    # document that isn't axe JSON at all should be told it lacks `testSubject`
    # and `findings`, not that some cosmetic field has the wrong type.
    test_subject: AxeTestSubject = Field(alias="testSubject")
    findings: AxeFindings
    # The identity fields (Slug source and observation time): optional because
    # a document may lack either, strict when present.
    name: str | None = None
    end_time: datetime | None = Field(default=None, alias="endTime")

    @field_validator("end_time", mode="before")
    @classmethod
    def parse_end_time(cls, value: Any) -> datetime | None:
        # `fromisoformat` rather than pydantic's own datetime coercion, so the
        # forms accepted before the parser moved here keep parsing (a `-0400`
        # numeric offset among them) and nothing new is accepted by accident.
        # An empty string is absent, not unreadable: the loader before the
        # move read every falsy value as absent, and the ADR promises what
        # parsed then still parses. Other falsy values (`0`, `False`) never
        # parsed and never appear in an export, so they stay invalid.
        if value is None or value == "":
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except (ValueError, TypeError) as exc:
            # Neither the value nor the stdlib's wording: this text reaches the
            # wire verbatim, and the file or request that carried the value is
            # already named by whoever reports it.
            raise ValueError("must be an ISO 8601 timestamp") from exc
        # An offset-less endTime is otherwise uncomparable against the UTC mtime
        # fallback and against sibling scans (the CLI compares their scanned_at
        # to pick the newest name, and the server pages Scan Runs by it) —
        # assume UTC.
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_axe_payload(raw: object) -> AxePayload:
    """Validate a decoded JSON document, surfacing failure as the domain's own
    invalid-axe-payload error mode rather than a framework `ValidationError`.
    The sole sanctioned crossing of the axe boundary. The caller keeps `raw`
    if it needs the Raw JSON: the model is the typed view, not the copy."""
    # `object`, not `dict`: the CLI hands over whatever `json.loads` produced,
    # and a list or a string is a verdict for the operator, not a type error.
    if not isinstance(raw, dict):
        raise InvalidAxePayloadError("document is not a JSON object")
    try:
        payload = AxePayload.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = " → ".join(str(part) for part in first["loc"])
        # A validator's own ValueError arrives wrapped as "Value error, <text>";
        # the bare text is the message, the wrapper is pydantic's.
        msg = str(first["ctx"]["error"]) if first["type"] == "value_error" else first["msg"]
        raise InvalidAxePayloadError(f"{loc}: {msg}") from exc
    return payload
