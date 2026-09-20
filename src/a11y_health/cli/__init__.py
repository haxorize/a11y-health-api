"""App onboarding CLI.

Pick by task:
- `a11y org-units list` / `a11y brands list` print id + name tables (org
  units also show their parent) — use them to find the `--org-unit-id` /
  `--brand-id` that `import` needs.
- `a11y org-units create <name> [--parent-id <id>]` creates a missing org
  unit and prints its id, so onboarding never has to leave the CLI.
- `a11y import <dir> --org-unit-id <id> --brand-id <id>` onboards a new app
  from a directory of YYYY-MM-DD subdirectories. Creates the app if missing,
  reuses if not. `--name` sets the display name at creation (must be
  derivation-equivalent to the axe JSON name; identity is locked once created).
- `a11y ingest <dir>` uploads a single scan to an existing app. Errors with
  a pointer to `import` if the app isn't registered.

Other admin mutations (app move/delete, org-unit reparent/delete) stay on
Swagger `/docs`.

The work splits into five concern modules, `_errors` being the shared error
base under the other four, and ADR 0043 records the split. This module is the
package's public face: the console entry point and that base type.
"""

from a11y_health.cli._errors import CliError
from a11y_health.cli._terminal import main

__all__ = ["CliError", "main"]
