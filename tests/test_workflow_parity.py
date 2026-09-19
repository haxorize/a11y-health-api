"""Where the workflow says a thing twice, the two copies still agree.

Two of those today: CI's per-tool lint steps against `make lint`'s membership,
and the uv setup step, which each of the three jobs writes out in full.

`make lint` is what a developer and the pre-commit hook run. CI runs the same
tools as separate steps so a red step names the tool rather than the target,
which means the membership is written twice — and until this module the
Makefile's own comment said so and left it there: "nothing checks the two
agree". A check added to one and not the other is then a check the hook runs
and CI does not, or the reverse, with nothing going red either way.

`make openapi-check` is deliberately outside this. CI runs it in the same job
for the same one-red-step-per-tool reason, but it is not a `make lint`
prerequisite and the hook invokes it separately, so it belongs to neither list.
The comparison is over the `lint-` prefixed targets alone.

The setup step was a YAML anchor in `lint` aliased by the other two jobs until
#152, which gave it one home at the price of an invisible ordering constraint:
an alias must follow its anchor, so moving `lint` below either other job made
the workflow unloadable, and an unloadable workflow creates no run for
`actionlint` to report from. Three copies plus this check trade that for a
failure mode that is merely red.
"""

import re
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parent.parent
_MAKEFILE = _REPO / "Makefile"
_WORKFLOW = _REPO / ".github/workflows/ci.yml"


def _make_lint_prerequisites() -> set[str]:
    # The recipe line, not the .PHONY line: both start with `lint`, and .PHONY
    # names every target in the file, so matching it would compare the whole
    # Makefile against CI's five steps.
    match = re.search(r"^lint:(?P<prerequisites>.*)$", _MAKEFILE.read_text(), re.MULTILINE)
    assert match is not None, "the Makefile declares no `lint:` target"
    return {word for word in match.group("prerequisites").split() if word.startswith("lint-")}


def _ci_lint_steps() -> set[str]:
    workflow = yaml.safe_load(_WORKFLOW.read_text())
    steps = workflow["jobs"]["lint"]["steps"]
    targets: set[str] = set()
    for step in steps:
        for target in re.findall(r"^make\s+(\S+)\s*$", str(step.get("run", "")), re.MULTILINE):
            if target.startswith("lint-"):
                targets.add(target)
    return targets


def test_both_readers_find_something() -> None:
    # Set equality between two empty sets is the failure this file exists to
    # prevent: a Makefile reworded past the regex, or a workflow whose lint job
    # is restructured, would otherwise pass by finding nothing on both sides.
    assert len(_make_lint_prerequisites()) >= 4, f"parsed only {_make_lint_prerequisites()} out of the Makefile"
    assert len(_ci_lint_steps()) >= 4, f"parsed only {_ci_lint_steps()} out of the workflow"


def test_ci_runs_exactly_what_make_lint_runs() -> None:
    from_make = _make_lint_prerequisites()
    from_ci = _ci_lint_steps()
    assert from_make == from_ci, (
        "`make lint` and CI's lint job have drifted — a tool one runs and the other does not.\n"
        f"  only in `make lint`: {sorted(from_make - from_ci) or 'none'}\n"
        f"  only in ci.yml:      {sorted(from_ci - from_make) or 'none'}\n"
        "Add the target to both, or give the tool a reason to live in one and say so here."
    )


def test_every_named_target_is_declared_phony() -> None:
    # A lint target shadowed by a file of the same name silently stops running,
    # which the parity check above cannot see: both lists would still agree.
    text = _MAKEFILE.read_text()
    phony = re.search(r"^\.PHONY:(?P<targets>.*)$", text, re.MULTILINE)
    assert phony is not None, "the Makefile declares no .PHONY line"
    declared = set(phony.group("targets").split())
    missing = sorted(target for target in _make_lint_prerequisites() | {"lint"} if target not in declared)
    assert not missing, f"lint targets missing from .PHONY: {missing}"


def _setup_uv_steps() -> list[dict]:
    workflow = yaml.safe_load(_WORKFLOW.read_text())
    return [
        step
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if "astral-sh/setup-uv" in str(step.get("uses", ""))
    ]


def test_every_job_sets_up_uv() -> None:
    # The floor. Every job here runs `uv`, so a job that lost its setup step
    # would fail on the first command rather than here — but a *reader* of the
    # agreement check below needs to know it compared three things and not one.
    workflow = yaml.safe_load(_WORKFLOW.read_text())
    assert len(_setup_uv_steps()) == len(workflow["jobs"]) == 3


def test_the_three_uv_setup_steps_are_identical() -> None:
    steps = _setup_uv_steps()
    first, *rest = steps
    mismatched = [step for step in rest if step != first]
    assert not mismatched, (
        "the uv setup step differs between jobs; it is written out per job and nothing else holds "
        f"the copies together.\n  first: {first}\n  differing: {mismatched}"
    )
