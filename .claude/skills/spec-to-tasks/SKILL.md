---
name: spec-to-tasks
description: Break a feature spec into vertical slices as GitHub issues or a local Markdown plan. Use when user wants to break down a feature spec, create implementation tickets, plan phases, or mentions "tracer bullets".
---

# Spec to Tasks

Break a feature spec into independently-grabbable vertical slices (tracer bullets).

## Process

### 1. Get the feature spec

Get the feature spec GitHub issue into context — ask the user for the issue number and fetch it with `gh issue view`, or skip if it's already in context from a prior step.

If you have not already explored the codebase, do so to understand the current architecture, existing patterns, and integration layers.

### 2. Identify durable architectural decisions

Before slicing, identify high-level decisions that are unlikely to change throughout implementation:

- Route structures / URL patterns
- Database schema shape
- Key data models
- Authentication / authorization approach
- Third-party service boundaries

Add or remove categories as appropriate for the feature.

### 3. Draft vertical slices

Break the spec into **tracer bullet** slices. Each slice is a thin vertical cut through ALL integration layers end-to-end, NOT a horizontal slice of one layer.

Rules:

- Each slice delivers a narrow but COMPLETE path through every layer (schema/migration, model, service, endpoint, tests)
- A completed slice is demoable or verifiable on its own
- Prefer many thin slices over few thick ones
- Do NOT include specific file names, function names, or implementation details likely to change
- DO include durable decisions: route paths, schema shapes, data model names

Mark each slice as **HITL** (needs your active decision-making) or **AFK** (can be handed to a Ralph loop). Prefer AFK where possible.

### 4. Quiz the user

Present the proposed breakdown as a numbered list. For each slice, show:

- **Title**: short descriptive name
- **Type**: HITL / AFK
- **Blocked by**: which other slices (if any) must complete first
- **Acceptance criteria addressed**: which numbered criteria from the parent spec

Ask the user:

- Does the granularity feel right? (too coarse / too fine)
- Are the dependency relationships correct?
- Should any slices be merged or split further?
- Are the correct slices marked as HITL and AFK?

Iterate until the user approves the breakdown.

### 5. Choose output format and create

Ask the user: **GitHub issues or local plan file?**

- **Issues**: Create using the template in [references/issue-template.md](references/issue-template.md). Create in dependency order so you can reference real issue numbers. Do NOT close or modify the parent feature spec issue.
- **Plan**: Write to `./plans/<feature-name>.md` using the template in [references/plan-template.md](references/plan-template.md). Create `./plans/` if it doesn't exist.

Present the draft to the user for review before creating.
