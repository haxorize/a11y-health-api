---
name: deepen
description: Explore the codebase for architectural friction, surface shallow-module candidates, and propose deepening refactors as GitHub issue RFCs. Use when reviewing architecture, finding coupling, identifying refactor opportunities, or wanting to improve testability.
---

# Deepen

Surface architectural friction and propose module-deepening refactors.

## Vocabulary

Use these terms exactly in every suggestion. Consistent language is the point — don't drift into "component," "service," or "boundary."

- **Module** — anything with an interface and an implementation (function, class, package, slice).
- **Interface** — everything a caller must know to use the module: types, invariants, error modes, ordering, config. Not just the type signature.
- **Implementation** — the code inside.
- **Depth** — leverage at the interface: a lot of behaviour behind a small interface. **Deep** = high leverage. **Shallow** = interface nearly as complex as the implementation.
- **Seam** — where an interface lives; a place behaviour can be altered without editing in place. (Use this, not "boundary" — boundary clashes with DDD's bounded context.)
- **Adapter** — a concrete thing satisfying an interface at a seam.
- **Leverage** — what callers get from depth.
- **Locality** — what maintainers get from depth: change, bugs, knowledge concentrated in one place.

Two principles that sharpen every proposal:

- **Deletion test.** Imagine deleting the module. If complexity vanishes, it was a pass-through. If complexity reappears across N callers, it was earning its keep. "Concentrates complexity" is the signal you want.
- **One adapter = hypothetical seam. Two adapters = real seam.** Don't introduce a port unless at least two adapters are justified (typically production + test). A single-adapter seam is just indirection.

## Workflow

### 1. Read project context, then check refactoring history

Read first, in parallel:

- `UBIQUITOUS_LANGUAGE.md` — use domain vocabulary in candidate descriptions ("the Score rollup module," not "the AggregatorService")
- `docs/adr/` — recorded decisions you should not re-litigate (proceed silently if absent)

Then check for prior architectural work:

- Run `gh issue list --state all --search "deepen OR refactor OR extract OR absorb"` to find existing refactor issues
- Run `git log --oneline -30` to scan recent commits for structural changes (extract, move, rename, refactor)
- Read any open refactor issues fully — understand the intent, not just the title

If an area was recently refactored, the bar for proposing another change is much higher. Ask: "Is this friction from an incomplete refactor, or from the refactor itself being wrong?" If incomplete, the right action is to update the existing issue, not file a new one.

### 2. Explore organically

Use the Agent tool with subagent_type=Explore to navigate the codebase. Do NOT follow rigid heuristics — explore and note where you experience friction:

- Where does understanding one concept require bouncing between many small files?
- Where are modules so shallow that the interface is nearly as complex as the implementation?
- Where have pure functions been extracted just for testability, but the real bugs hide in how they're called?
- Where do tightly-coupled modules create integration risk in the seams between them?
- Which parts of the codebase are untested or hard to test?
- Where do domain terms from UBIQUITOUS_LANGUAGE.md leak across module boundaries?

The friction you encounter IS the signal.

### 3. Consolidate and present candidates

Group related findings into coherent candidates — don't present overlapping or sub-issues separately. **Cross-reference against existing issues found in step 1.** If a candidate overlaps with an existing issue, say so explicitly — propose updating that issue rather than filing a new one.

**ADR conflicts:** if a candidate contradicts an existing ADR, only surface it when the friction is real enough to warrant revisiting the ADR. Mark it clearly (e.g., _"contradicts ADR-0007 — but worth reopening because…"_). Don't list every theoretical refactor an ADR forbids.

Present a numbered list of deepening opportunities. For each candidate, show:

- **Cluster**: Which modules/concepts are involved
- **Why they're coupled**: Shared types, call patterns, co-ownership of a concept
- **Prior work**: Any existing issues or recent refactors in this area (from step 1)
- **Current test coverage**: What exists, what's missing, what's fragile
- **Deepening direction**: What a deeper module would hide and what it would expose

Do NOT propose interfaces yet. Ask: "Which of these would you like to explore?"

### 4. User picks a candidate

### 5. Frame the problem space

Write a user-facing explanation of the chosen candidate:

- The constraints any new interface would need to satisfy
- The dependencies it would need to rely on
- A rough illustrative code sketch to make the constraints concrete — this is not a proposal, just a way to ground the discussion

If framing reveals this isn't a deepening candidate (e.g., modules are thin for good reason, or the friction is a bug/test gap rather than an architecture problem), say so and offer alternatives — a bug fix issue, test coverage issue, or skipping it entirely.

### 6. Propose a design

Present one recommended interface design:

- Interface signature (types, methods, params)
- Usage example showing how callers use it
- What complexity it hides internally
- What existing tests would be replaced by boundary tests
- Trade-offs

Be opinionated — the user wants a strong recommendation, not a menu.

Offer to run `/grill-me` on the design if the user wants to stress-test it.

### 7. Create or update issue(s)

Once the user approves, either **update an existing issue** or **create a new one** using `gh` (title and body only — no labels or assignees).

- If step 1 found an existing issue that covers this candidate, update it with a comment or revised body rather than filing a duplicate.
- If the candidate is net-new, create an issue. Do NOT ask the user to review before creating — just create it and share the URL.

Use the template below for refactor RFCs; adapt the format for simpler issues.

## Issue template

```markdown
## Problem

- Which modules are shallow and tightly coupled
- What integration risk exists in the seams between them
- Why this makes the codebase harder to navigate and maintain

## Proposed Interface

- Interface signature (types, methods, params)
- Usage example showing how callers use it
- What complexity it hides internally

## Testing Strategy

- New boundary tests to write (behaviors to verify at the interface)
- Tests to update or remove (shallow module tests that become redundant, or tests that need renaming/restructuring)

## Implementation Decisions

Durable architectural guidance, NOT coupled to current file paths:

- What the module should own (responsibilities)
- What it should hide (implementation details)
- What it should expose (the interface contract)
- How callers should migrate to the new interface

## Out of Scope

What is explicitly not part of this refactor.
```
