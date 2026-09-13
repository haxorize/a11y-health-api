# Astral-only Python toolchain: uv, ruff, ty, on a hard Python 3.14 floor

Package management, linting/formatting, and type checking all run on Astral tools: `uv` for dependencies and command running, `ruff` for lint+format, `ty` for type checking. No pip, poetry, mypy, pyright, black, isort, or flake8.

Considered and rejected:
- **Mature stack (poetry + mypy + black + isort + flake8)**: the conventional choice. Rejected because the Astral stack is meaningfully faster, runs as one cohesive toolchain, and removes the per-tool config overhead. The speedup matters most on every-save type checking and pre-commit hooks, where felt latency dominates.
- **`pyright` instead of `ty`**: the closest competitor on type-checker capability. `ty` is the explicit choice despite being pre-1.0 because we want the whole toolchain to share an upgrade cadence, error-message style, and configuration surface. Re-evaluate if `ty` stalls or breaks compatibility.

The lock-in is real: `ty`'s pre-1.0 status means we may hit type-system gaps or behavioral changes that mypy/pyright wouldn't have. The bet is that the ergonomic win across the toolchain pays for that risk.

Revisit when: "`ty` stalls or breaks compatibility" — pinned at 0.0.75 when this line was written, so a later sweep can tell a stall from ordinary currency.

## Amendments

- **2026-09-12 (#146)** — **Python 3.14 is a hard floor everywhere, reversing the portability climbdown of `ee6a6cd`.** That April commit lowered the requirement to 3.13 "for cross-machine portability"; `01626f1` (2026-08-05) put it back at 3.14 across `.python-version`, `requires-python`, the ruff target, `ty`, and all four CI refs. The reason is the dev-machine security policy plus general currency, and the reason it can be *hard* rather than a floor with a fallback is that nothing else runs this code — local development and CI only, no published package and no third-party installer to strand.
- **2026-09-12 (#146)** — This is the same bet the record above makes, one layer down: currency over portability, paid for by a small blast radius. A reader who finds `ee6a6cd` reversed without a reason would reasonably re-lower the floor the next time a machine lags.
