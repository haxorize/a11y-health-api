"""The Classification value object and the closed vocabulary that names it.

See `docs/architecture.md` ("The layers") for why this lives in `models/`, ADR
0031 for the wire shape, its four production consumers, and the placement
argument that put the vocabulary here, that record's 2026-08-05 (#131 review)
amendment for the module's closed charter and the import-time drift guard, and
`DOMAIN.md` for Classification and Classification Token.

Reading a tag's *shape* — a Category, a WCAG Criterion — is
`schemas/_tag_parsing.py`'s job.
"""

import logging
from collections.abc import Iterable
from typing import Literal, Self, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

logger = logging.getLogger(__name__)


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
        # The rule is DOMAIN.md's Classification entry.
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
        # Wire shape == stored shape: clients generated before this model was
        # typed validate members as strings, so absent members are omitted,
        # never null.
        return {k: v for k, v in handler(self).items() if v is not None}


ClassificationToken = Literal[
    "wcag2a",
    "wcag2aa",
    "wcag2aaa",
    "wcag21a",
    "wcag21aa",
    "wcag21aaa",
    "wcag22a",
    "wcag22aa",
    "wcag22aaa",
    "best-practice",
]


_TOKEN_TO_CLASSIFICATION: dict[str, Classification] = {
    "wcag2a": Classification(standard="wcag", version="2.0", level="A"),
    "wcag2aa": Classification(standard="wcag", version="2.0", level="AA"),
    "wcag2aaa": Classification(standard="wcag", version="2.0", level="AAA"),
    "wcag21a": Classification(standard="wcag", version="2.1", level="A"),
    "wcag21aa": Classification(standard="wcag", version="2.1", level="AA"),
    "wcag21aaa": Classification(standard="wcag", version="2.1", level="AAA"),
    "wcag22a": Classification(standard="wcag", version="2.2", level="A"),
    "wcag22aa": Classification(standard="wcag", version="2.2", level="AA"),
    "wcag22aaa": Classification(standard="wcag", version="2.2", level="AAA"),
    "best-practice": Classification(standard="best-practice"),
}

# The Literal feeds the OpenAPI enum; the map feeds storage and the filter. A
# missing map entry would 500 on a contractually valid token, so drift fails at
# import instead (an explicit raise, not an assert — asserts vanish under
# python -O).
if set(get_args(ClassificationToken)) != _TOKEN_TO_CLASSIFICATION.keys():
    raise RuntimeError("ClassificationToken and _TOKEN_TO_CLASSIFICATION have drifted")


# Classification is frozen, so its own value-equality keys the reverse lookup.
_CLASSIFICATION_TO_TOKEN: dict[Classification, ClassificationToken] = {
    _TOKEN_TO_CLASSIFICATION[token]: token for token in get_args(ClassificationToken)
}


def classification_options(
    classifications: Iterable[Classification],
) -> list[tuple[ClassificationToken, Classification]]:
    """Distinct (token, Classification) pairs, in vocabulary order. A
    Classification that earns no token — a raw-SQL backfilled WCAG 3.0, say — is
    dropped with a warning: the filter can't query what it can't name."""
    present: set[ClassificationToken] = set()
    for classification in classifications:
        token = _CLASSIFICATION_TO_TOKEN.get(classification)
        if token is None:
            logger.warning("Omitting off-vocabulary classification %r from filter options", classification)
            continue
        present.add(token)
    return [(token, _TOKEN_TO_CLASSIFICATION[token]) for token in get_args(ClassificationToken) if token in present]


def classifications_in(candidates: Iterable[str]) -> list[Classification]:
    """The Classifications these candidates name, in the order given. Takes bare
    `str` rather than `ClassificationToken` and drops what it cannot name: the
    caller's vocabulary is open-ended, and only this vocabulary decides what
    counts."""
    named = (_TOKEN_TO_CLASSIFICATION.get(candidate) for candidate in candidates)
    return [classification for classification in named if classification is not None]
