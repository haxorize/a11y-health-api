---
name: deepen
description: Explore the codebase for architectural friction, surface shallow-module candidates, and propose deepening refactors as GitHub issue RFCs. Use when reviewing architecture, finding coupling, identifying refactor opportunities, or wanting to improve testability.
---

# Deepen

Surface architectural friction and propose module-deepening refactors.

## Workflow

### 1. Explore organically

Use the Agent tool with subagent_type=Explore to navigate the codebase. Do NOT follow rigid heuristics — explore and note where you experience friction:

- Where does understanding one concept require bouncing between many small files?
- Where are modules so shallow that the interface is nearly as complex as the implementation?
- Where have pure functions been extracted just for testability, but the real bugs hide in how they're called?
- Where do tightly-coupled modules create integration risk in the seams between them?
- Which parts of the codebase are untested or hard to test?
- Where do domain terms from UBIQUITOUS_LANGUAGE.md leak across module boundaries?

The friction you encounter IS the signal.

### 2. Consolidate and present candidates

Group related findings into coherent candidates — don't present overlapping or sub-issues separately. Present a numbered list of deepening opportunities. For each candidate, show:

- **Cluster**: Which modules/concepts are involved
- **Why they're coupled**: Shared types, call patterns, co-ownership of a concept
- **Current test coverage**: What exists, what's missing, what's fragile
- **Deepening direction**: What a deeper module would hide and what it would expose

Do NOT propose interfaces yet. Ask: "Which of these would you like to explore?"

### 3. User picks a candidate

### 4. Frame the problem space

Write a user-facing explanation of the chosen candidate:

- The constraints any new interface would need to satisfy
- The dependencies it would need to rely on
- A rough illustrative code sketch to make the constraints concrete — this is not a proposal, just a way to ground the discussion

If framing reveals this isn't a deepening candidate (e.g., modules are thin for good reason, or the friction is a bug/test gap rather than an architecture problem), say so and offer alternatives — a bug fix issue, test coverage issue, or skipping it entirely.

### 5. Propose a design

Present one recommended interface design:

- Interface signature (types, methods, params)
- Usage example showing how callers use it
- What complexity it hides internally
- What existing tests would be replaced by boundary tests
- Trade-offs

Be opinionated — the user wants a strong recommendation, not a menu.

Offer to run `/grill-me` on the design if the user wants to stress-test it.

### 6. Create issue(s)

Once the user approves, create the appropriate issue(s) using `gh issue create` (title and body only — no labels or assignees). This might be a single refactor RFC, multiple issues (e.g., merged candidates), or a simpler bug/test ticket if the candidate turned out not to need deepening.

Do NOT ask the user to review before creating — just create it and share the URL. Use the template below for refactor RFCs; adapt the format for simpler issues.

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
