# Incompletes are excluded from Page Health and Score

axe DevTools produces three rule outcomes that we persist: violations, incompletes (axe could not determine automatically — needs manual review), and passes/inapplicables (preserved in raw JSON only). Only **violations** affect Page Health and Score. Incompletes are stored as Rule Findings with `type = INCOMPLETE` so reviewers can triage them, but they do not count toward any aggregate metric.

Considered and rejected:
- **Count incompletes at a fractional weight**: the obvious "be conservative" move. Rejected because the weight would be arbitrary, and incompletes have no measured failure — many resolve to "pass" on review. Mixing them in pollutes the score.
- **Treat incompletes as violations until reviewed**: rejected for the same reason. It produces noisy scores that swing on review backlog rather than actual accessibility.
- **Compute two parallel scores (with vs. without incompletes)**: rejected as premature; consumers consistently want a single decision-grade number.

The line between violation and incomplete is owned by axe, not us. If a future review workflow promotes incompletes to violations, that surfaces in the score through the normal Rule Finding path.
