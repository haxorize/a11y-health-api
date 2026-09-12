# Deferred dependency bumps

One line per package the last `upgrade-deps` run audited and did not take. The next run's discovery step greps these back and re-audits each on or after its review-by date.

Run of 2026-09-06. Publisher note: fastapi, sqlalchemy, pydantic-core, greenlet, mako, pygments, annotated-types, annotated-doc, ruff, and ty publish without a PyPI provenance attestation; they were taken on the user's decision after each tarball diff matched its changelog. Expect the same question next run.

## Review-by 2026-09-09 (7-day floor from publish)

- ty 0.0.75 -> 0.0.78 — 0.0.78 published 2026-09-02; 0.0.75 (2026-08-26) was the newest past the floor and was taken. Unattested.
- ruff 0.16.5 -> 0.16.6 — 0.16.6 published 2026-09-03; 0.16.5 (2026-08-27) taken. Unattested.

## Review-by 2026-09-11

- alembic 1.18.5 -> 1.19.2 — published 2026-09-04. Do not substitute 1.19.0 or 1.19.1: they enable the CHECK-constraint autogenerate plugin by default (false-positive risk against this repo's named CHECK constraints and CI's drift check); 1.19.2 turns it off. Unattested.

## Review-by 2026-09-12

- anyio 4.14.2 -> 4.15.1 — published 2026-09-05; attested (agronholm/anyio). 4.15.0 (2026-09-02) is not a substitute: 4.15.1 fixes its lazy-import regression. New floor typing_extensions>=4.16 on py<3.15 (lock has 4.16.0).
