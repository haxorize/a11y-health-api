"""Dump the OpenAPI schema to openapi.json at the repo root, or to a given path.

The path argument is what `make openapi-check` generates through, so the check
can read a spec without overwriting the one it is checking.
"""

import json
import sys
from pathlib import Path

from a11y_health.main import app


def main() -> None:
    spec = app.openapi()
    default = Path(__file__).resolve().parent.parent / "openapi.json"
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    output.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    print(f"wrote {output} ({len(spec['paths'])} paths)")


if __name__ == "__main__":
    main()
