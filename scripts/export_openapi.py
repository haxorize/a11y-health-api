"""Dump the OpenAPI schema to openapi.json at the repo root."""

import json
from pathlib import Path

from a11y_health.main import app


def main() -> None:
    spec = app.openapi()
    output = Path(__file__).resolve().parent.parent / "openapi.json"
    output.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    print(f"wrote {output} ({len(spec['paths'])} paths)")


if __name__ == "__main__":
    main()
