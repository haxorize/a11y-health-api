---
name: adr
description: Architecture Decision Records for this project. Use when recording a design decision, capturing rationale for a non-obvious choice, or backfilling ADRs from history.
---

# ADR

Lightweight Architecture Decision Records — capture *why* a non-obvious design choice was made, in the smallest form that preserves the rationale.

ADRs live in `docs/adr/` with sequential numbering: `0001-slug.md`, `0002-slug.md`, etc. Create the directory lazily — only when the first ADR is written.

## When to write an ADR

All three criteria must hold. If any one is missing, skip it.

1. **Hard to reverse** — undoing this later carries real cost (schema migration, dependency change, methodology shift).
2. **Surprising without context** — a future reader (or AFK agent) will look at the code and wonder "why did they do it this way?"
3. **Result of a real trade-off** — there were genuine alternatives and one was picked for specific reasons.

If the decision is easy to reverse, skip — you'll just reverse it. If it's not surprising, nobody will wonder. If there was no real alternative, there's nothing to record beyond "we did the obvious thing."

### What qualifies

- **Architectural shape** — "transactional rollback for test isolation," "ScoreSnapshot append-only model"
- **Technology choices that carry lock-in** — toolchain, framework, database, deployment target
- **Boundary and scope decisions** — what each module owns, what it doesn't
- **Deliberate deviations from the obvious path** — anything where a reasonable reader would assume the opposite (e.g., BIGINT PKs instead of UUIDs, deferred JSONB by access pattern)
- **Constraints not visible in the code** — compliance, partner contracts, organizational requirements
- **Rejected alternatives when the rejection is non-obvious** — record what you considered and why you didn't pick it, otherwise someone will suggest it again later

### What doesn't qualify

- Bug fixes (commit messages own this)
- Reversible style choices (CLAUDE.md or formatter config own this)
- Personal-preference workflow choices (memory file owns this)
- Routine feature additions (PR descriptions own this)

## Workflow: record one ADR

### 1. Apply the gate

Confirm out loud which of the three criteria the decision meets, and which alternatives were considered. If the gate fails, stop and tell the user.

### 2. Number and slug

Scan `docs/adr/` for the highest existing number; increment by one. Slug is a short kebab-case summary of the decision.

### 3. Draft

Default form is 1-3 sentences. Use this template:

```md
# <Short title>

<1-3 sentences: what was the context, what did we decide, and why. Mention the rejected alternatives if their rejection wasn't obvious.>
```

Optional sections — only when they add real value, not for completeness:

- **Status** frontmatter (`proposed | accepted | superseded by ADR-NNNN`) — useful when revisiting
- **Considered Options** — only when rejected alternatives are worth remembering in detail
- **Consequences** — only when downstream effects are non-obvious

### 4. Show and save

Show the draft to the user. Save to `docs/adr/<NNNN>-<slug>.md` once approved.

## Workflow: backfill from history

Run this once to seed the ADR log, then archive the workflow.

### 1. Gather signals

Read in parallel:

- `git log --oneline | head -100` for recent design-shaped commits
- `~/.claude/projects/-Users-haxorize-code-src-a11y-health-api/memory/MEMORY.md` and any project-flavored entries
- Closed feature spec issues (`gh issue list --state closed --label spec`)
- `CLAUDE.md`, `UBIQUITOUS_LANGUAGE.md`, key model and service files

### 2. Draft candidate list

For each candidate, list:

- **Title** — short kebab-case slug
- **Why it qualifies** — which of the three criteria it meets
- **Rationale source** — where the "why" comes from (commit, memory, file, conversation)

Prefer fewer high-quality ADRs over many marginal ones.

### 3. Walk the user through each candidate

One at a time. For each: confirm the gate holds, ask the user to refine the rationale, draft the ADR, save.

If the user rejects a candidate, drop it and move on — don't argue.

### 4. Stop

Once the candidate list is exhausted, stop. Don't keep mining for more — the goal is to seed the log, not exhaustively document every past choice.
