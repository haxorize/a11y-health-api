"""The Classification value object — a layer-neutral leaf, importable by both
the schemas that serve it and the column type that enforces its compact stored
shape (ADR 0031). Parsing from axe tags and the query-token vocabulary stay in
`schemas/_tag_parsing.py`.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, SerializerFunctionWrapHandler, model_serializer, model_validator


class Classification(BaseModel):
    # Frozen because _TOKEN_TO_CLASSIFICATION hands out shared instances. Extras
    # forbidden so a writer with a stray member is refused at the column guard,
    # not silently truncated by stored().
    model_config = ConfigDict(frozen=True, extra="forbid")

    standard: Literal["wcag", "best-practice"]
    version: str | None = None
    level: Literal["A", "AA", "AAA"] | None = None

    @model_validator(mode="after")
    def _members_match_standard(self) -> Self:
        # DOMAIN.md: a WCAG Classification carries a version and level; a
        # best-practice Classification carries neither.
        if self.standard == "wcag":
            if self.version is None or self.level is None:
                raise ValueError("a wcag Classification carries a version and a level")
        elif self.version is not None or self.level is not None:
            raise ValueError("a best-practice Classification carries neither a version nor a level")
        return self

    def stored(self) -> dict[str, str]:
        """The canonical JSONB shape — no null members, so the filter's GIN
        containment targets and persisted rows can never disagree."""
        return self.model_dump(exclude_none=True)

    @model_serializer(mode="wrap")
    def _omit_none_members(self, handler: SerializerFunctionWrapHandler):
        # Wire shape == stored shape: clients generated before this model was typed
        # validate members as strings, so absent members are omitted, never null.
        return {k: v for k, v in handler(self).items() if v is not None}
