---
name: write-feature-spec
description: Feature spec authoring for this project. Use when the user wants to write a feature spec, plan a new feature, or design a module.
---

# Feature Spec

If the conversation already covers the problem and direction in detail (e.g., you've been discussing it for a while and now just want to commit it to an issue), skip the interview steps below and synthesize directly from context. Still do §4 (propose approaches) and §6's self-review — those guard against blind spots regardless of how much context you have.

## Workflow

### 1. Get the problem statement

Ask the user for a brief description (2-3 sentences) of the problem they want to solve and any rough direction for a solution.

### 2. Explore the codebase

Verify the user's assertions and understand the current state. Identify existing modules, schemas, and patterns that are relevant to the problem.

### 3. Interview

Ask questions one at a time. For each question, provide your recommended answer. If a question can be answered by exploring the codebase, explore the codebase instead of asking.

Walk down each branch of the design tree, resolving dependencies between decisions one-by-one. Cover:

- Scope boundaries (what's in, what's out)
- Data model and schema changes
- API contracts (endpoints, request/response shapes)
- Integration points with existing modules
- Error handling and edge cases
- Migration strategy (if modifying existing behavior)

### 4. Propose approaches

Present 2-3 distinct approaches with their trade-offs. Lead with your recommendation and explain why. Let the user pick or push back before committing to a direction — this guards against converging on the first reasonable design.

After the user picks, apply the ADR gate to the chosen approach (hard to reverse + surprising + real trade-off). If it qualifies, record it via the `adr` skill before drafting the spec — the spec will then cite the ADR rather than restating the rationale.

### 5. Identify modules

Sketch out the major modules to build or modify. Look for opportunities to extract deep modules that can be tested in isolation.

Check with the user that these modules match their expectations. Check which modules they want tests written for.

### 6. Draft and submit

Write the feature spec using the template in [references/spec-template.md](references/spec-template.md).

Self-review the draft before showing it to the user:

- Placeholders — any "TBD", "TODO", or incomplete sections?
- Contradictions — do any sections disagree with each other?
- Scope — is this focused enough for one spec, or does it need decomposition?
- Ambiguity — could any requirement be read two ways? Pick one and make it explicit.

Fix issues inline. Then present the draft to the user for review. Iterate until they approve.

Submit as a GitHub issue (title and body only — no labels or assignees).
