---
name: write-feature-spec
description: Create a feature spec through user interview, codebase exploration, and module design, then submit as a GitHub issue. Use when user wants to write a feature spec, plan a new feature, or design a module.
---

# Feature Spec

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

### 4. Identify modules

Sketch out the major modules to build or modify. Look for opportunities to extract deep modules that can be tested in isolation.

Check with the user that these modules match their expectations. Check which modules they want tests written for.

### 5. Draft and submit

Write the feature spec using the template in [references/spec-template.md](references/spec-template.md).

Present the draft to the user for review before submitting. Iterate until they approve.

Submit as a GitHub issue (title and body only — no labels or assignees).
