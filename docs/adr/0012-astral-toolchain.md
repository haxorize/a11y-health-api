# Astral-only Python toolchain: uv, ruff, ty

Package management, linting/formatting, and type checking all run on Astral tools: `uv` for dependencies and command running, `ruff` for lint+format, `ty` for type checking. No pip, poetry, mypy, pyright, black, isort, or flake8.

Considered and rejected:
- **Mature stack (poetry + mypy + black + isort + flake8)**: the conventional choice. Rejected because the Astral stack is meaningfully faster, runs as one cohesive toolchain, and removes the per-tool config overhead. The speedup matters most on every-save type checking and pre-commit hooks, where felt latency dominates.
- **`pyright` instead of `ty`**: the closest competitor on type-checker capability. `ty` is the explicit choice despite being pre-1.0 because we want the whole toolchain to share an upgrade cadence, error-message style, and configuration surface. Re-evaluate if `ty` stalls or breaks compatibility.

The lock-in is real: `ty`'s pre-1.0 status means we may hit type-system gaps or behavioral changes that mypy/pyright wouldn't have. The bet is that the ergonomic win across the toolchain pays for that risk.
