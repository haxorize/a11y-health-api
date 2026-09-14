"""Dump the OpenAPI schema to openapi.json at the repo root, or to a given path.

The path argument is what `make openapi-check` generates through, so the check
can read a spec without overwriting the one it is checking.
"""

import json
import sys
from pathlib import Path

import a11y_health.config as config

# Three settings reach the emitted spec: PROJECT_NAME becomes info.title,
# VERSION becomes info.version, and API_V1_PREFIX prefixes every path. They are
# declared in config.py and absent from .env.example, so they are the repo's
# identity rather than an operator's knob — but Settings still reads them from
# .env and from the shell. A developer who sets one would regenerate a spec only
# they can produce, and `make openapi-check` would then call the committed spec
# stale and tell them to commit theirs. Rebinding the singleton from the
# declared defaults, before main.py binds it, makes the artifact the same on
# every machine. Init arguments outrank both sources, so nothing else is needed.
_IDENTITY = ("PROJECT_NAME", "VERSION", "API_V1_PREFIX")
config.settings = config.Settings(**{name: config.Settings.model_fields[name].default for name in _IDENTITY})

from a11y_health.main import app  # noqa: E402 — must follow the settings rebind above


def main() -> None:
    spec = app.openapi()
    default = Path(__file__).resolve().parent.parent / "openapi.json"
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    output.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    print(f"wrote {output} ({len(spec['paths'])} paths)")


if __name__ == "__main__":
    main()
