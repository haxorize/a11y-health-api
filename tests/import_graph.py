"""Reading a module's imports off its source, for the suite's topology guards.

Several tests ask "what does this module import?" against different rules —
which private modules are reached from outside their package
(`test_import_honesty`), which siblings a scoring module may touch
(`test_score_snapshot`), whether an endpoint reaches the Existence Guard
(`test_existence`). The rules differ; the walk does not, and a walk that quietly
missed an import spelling would weaken every rule sharing it at once.

Named publicly because its consumers sit in sibling test packages — see
[ADR 0038](../docs/adr/0038-package-private-underscore-enforced-repo-wide.md).
"""

import ast
from collections.abc import Container, Iterable
from pathlib import Path


def module_name(path: Path, root: Path, root_name: str) -> str:
    parts = path.relative_to(root).with_suffix("").parts
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join((root_name, *parts))


def package_of(module: str) -> str:
    return module.rpartition(".")[0]


def packages_in(names: Iterable[str]) -> frozenset[str]:
    """Which of `names` are packages — anything another name sits under. A
    package whose `__init__` is its only module therefore reads as a leaf, and a
    relative import *from* it would resolve one level high; no such package
    exists under `src/`."""
    return frozenset(package_of(name) for name in names) - {""}


def imported_modules(source: str, importer: str, packages: Container[str] = frozenset()) -> set[str]:
    """Every module name the source's imports could name, relative spellings
    resolved against `importer`. Pass `packages` when the importer may itself be
    a package; the default reads it as a leaf module.

    AST rather than source substrings, and every path an import *could* name:
    `from a.b import c` leaves c ambiguous between a submodule and a symbol, so
    both readings are offered and the caller keeps the one that exists.
    """
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                # A package's `__init__` is already inside itself, so one dot
                # means the package; for a leaf module it means its parent.
                anchor = importer if importer in packages else package_of(importer)
                for _ in range(node.level - 1):
                    anchor = package_of(anchor)
                base = f"{anchor}.{base}" if base else anchor
            if not base:
                continue
            modules.add(base)
            modules.update(f"{base}.{alias.name}" for alias in node.names)
    return modules
