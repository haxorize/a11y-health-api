# Plan Template

Use this template when writing the local Markdown plan file to `./plans/<feature-name>.md`.

```markdown
# Plan: <Feature Name>

> Source feature spec: #<issue-number>

## Architectural decisions

Durable decisions that apply across all phases:

- **Routes**: ...
- **Schema**: ...
- **Key models**: ...
- (add/remove sections as appropriate)

---

## Phase 1: <Title> [AFK]

**Acceptance criteria addressed**: 1, 2

### What to build

A concise description of this vertical slice. Describe the end-to-end behavior, not layer-by-layer implementation.

### Acceptance criteria

- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3

### Blocked by

None - can start immediately

---

## Phase 2: <Title> [HITL]

**Acceptance criteria addressed**: 3, 4, 5

### What to build

...

### Acceptance criteria

- [ ] ...

### Blocked by

Phase 1

<!-- Repeat for each phase -->
```
