"""Scoring Vocabulary — the single source of scoring meaning.

Owns the Page Health ordering (worst -> best), the health weights, and the
total Impact -> Page Health mapping. The scoring engine imports these and the
read-only vocabulary endpoint serves them, so no consumer re-derives or
hard-codes them (ADR 0020). See docs/architecture.md ("The scoring & rollup
model").
"""

from a11y_health.models.enums import Impact, PageHealth

PAGE_HEALTH_ORDERING: tuple[PageHealth, ...] = (
    PageHealth.CRITICAL,
    PageHealth.SERIOUS,
    PageHealth.FAIR,
    PageHealth.GOOD,
)

# Derived, never hand-written: rank 0 is worst. Reordering PAGE_HEALTH_ORDERING
# is the one way to change what "worse" means.
PAGE_HEALTH_RANK: dict[PageHealth, int] = {health: rank for rank, health in enumerate(PAGE_HEALTH_ORDERING)}

PAGE_HEALTH_WEIGHT: dict[PageHealth, float] = {
    PageHealth.CRITICAL: 0.0,
    PageHealth.SERIOUS: 0.4,
    PageHealth.FAIR: 0.8,
    PageHealth.GOOD: 1.0,
}

IMPACT_TO_PAGE_HEALTH: dict[Impact, PageHealth] = {
    Impact.CRITICAL: PageHealth.CRITICAL,
    Impact.SERIOUS: PageHealth.SERIOUS,
    Impact.MODERATE: PageHealth.FAIR,
    Impact.MINOR: PageHealth.GOOD,
}
