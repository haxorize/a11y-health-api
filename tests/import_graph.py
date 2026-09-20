"""Reading imports off Python source, for the suite's topology guards.

Several tests ask "what does this module import?" against different rules —
which private modules are reached from outside their package
(`test_import_honesty`), which service modules may import which siblings
(`test_sibling_imports`), whether an endpoint reaches the Existence Guard
(`test_existence`), whether any src caller from-imports a rollup raiser
(`test_declaration_honesty`), whether every module is reached from an entry
point (`test_reachability`), which modules import the classification vocabulary
(`test_classification`). The rules differ; the reading does not, and a reader
that quietly missed an import spelling would weaken every rule sharing it at
once.

The tree walk is `package_sources`, and `source_paths_importing` is that walk
with the rule left to the caller, for the guards that only need the offending
paths.

Named publicly because a consumer sits in a sibling test package
(`tests/core/test_existence.py`), which a private name would shut out — see
[ADR 0038](../docs/adr/0038-package-private-underscore-enforced-repo-wide.md).
"""

import ast
from collections.abc import Callable, Container, Iterable
from pathlib import Path
from types import ModuleType
from typing import NamedTuple


class Module(NamedTuple):
    path: Path
    name: str
    source: str


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


def resolved_modules(imported: Iterable[str], known: Container[str]) -> set[str]:
    """The modules in `known` that `imported` reaches. `from a.b import c`
    offers both `a.b` and `a.b.c`, so only the spellings that exist are kept —
    and reaching a submodule reaches every package above it, because their
    `__init__` modules run first."""
    found: set[str] = set()
    for name in imported:
        parts = name.split(".")
        for depth in range(1, len(parts) + 1):
            candidate = ".".join(parts[:depth])
            if candidate in known:
                found.add(candidate)
    return found


def assert_descends(modules: Iterable[Module], root: Path) -> None:
    """Pin that a walk under `root` descended. Every guard built on the walk
    asserts on an empty offender list, which cannot tell "nothing violates the
    rule" from "the walk never looked". Read off the paths rather than
    `packages_in`, which counts a subpackage holding only an `__init__` as a
    leaf. Both roots nest; a walk that stopped descending (a non-recursive
    glob, a root scoped at the wrong level) would disarm every rule sharing it
    while the suite stayed green."""
    assert any(module.path.parent != root for module in modules), (
        f"walk under {root} reached nothing below the top level — it is not descending, so its guards pass vacuously"
    )


def package_root(package: ModuleType) -> Path:
    assert package.__file__ is not None, f"{package.__name__} has no __file__ — a namespace package cannot be walked"
    return Path(package.__file__).parent


def package_sources(package: ModuleType) -> list[Module]:
    """Every module under `package`, sorted by path, each with the name it
    would be imported as and its source.

    A list, not a mapping keyed by module name: two files can resolve to one
    name — a stale `owner.py` left beside a new `owner/__init__.py` — and a
    mapping silently drops one of them, which reads as "nothing to report" to
    every guard built on it (#138).

    Takes the package rather than a root and a name so the two cannot be
    mispaired, which would yield wrong dotted names and a guard that passes
    while looking at the wrong tree.
    """
    root = package_root(package)
    return [
        Module(path, module_name(path, root, package.__name__), path.read_text()) for path in sorted(root.rglob("*.py"))
    ]


def source_paths_importing(package: ModuleType, matches: Callable[[set[str]], bool]) -> list[str]:
    """Paths under `package`, relative and sorted, of the modules whose import
    set satisfies `matches` — the walk with the rule left to the caller.

    Resolving relative spellings needs the whole tree read first, which is why
    this walks rather than testing one file at a time.
    """
    root = package_root(package)
    modules = package_sources(package)
    packages = packages_in(module.name for module in modules)
    assert_descends(modules, root)
    return sorted(
        str(module.path.relative_to(root))
        for module in modules
        if matches(imported_modules(module.source, module.name, packages))
    )
