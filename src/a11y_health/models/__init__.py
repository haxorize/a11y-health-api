"""The metadata registry, not an import surface: `migrations/env.py` and
`tests/conftest.py` star-import this list so every model is registered on
`Base.metadata`. A model module omitted here still imports and type-checks, and
is invisible to Alembic autogeneration and to `create_all`.
"""

from a11y_health.models.app import App
from a11y_health.models.brand import Brand
from a11y_health.models.node_finding import NodeFinding
from a11y_health.models.org_unit import OrgUnit
from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import RuleFinding
from a11y_health.models.scan_run import ScanRun
from a11y_health.models.score_snapshot import ScoreSnapshot

__all__ = ["App", "Brand", "NodeFinding", "OrgUnit", "PageResult", "RuleFinding", "ScanRun", "ScoreSnapshot"]
