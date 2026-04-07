---
name: write-skill
description: Create new agent skills with proper structure and size constraints. Use when user wants to create, write, or build a new skill.
---

# Writing Skills

## Process

1. **Gather requirements** — what domain, what use cases, any reference material?
2. **Draft the skill** — SKILL.md with references if needed
3. **Review with user** — present draft, iterate

## Skill structure

```
skill-name/
├── SKILL.md              # Main instructions (required, ≤150 lines)
├── references/           # Detailed docs (if needed)
│   ├── topic-a.md        # Each ≤200 lines
│   └── topic-b.md
└── scripts/              # Deterministic helpers (if needed)
    └── helper.py
```

## SKILL.md template

```md
---
name: skill-name
description: Brief description. Use when [specific triggers].
---

# Skill Name

## Quick start

[Minimal working example or key conventions]

## Workflows

[Step-by-step processes for common tasks]

## References

[Links to reference files: See [references/topic.md](references/topic.md)]
```

## Size constraints

- **SKILL.md**: ≤150 lines. If it grows past this, move detail into `references/`
- **Reference files**: ≤200 lines each. Split by topic, not arbitrarily
- **Description**: ≤1024 chars. First sentence: what it does. Second: "Use when [triggers]."

## Description guidelines

The description is the **only thing the agent sees** when deciding which skill to load. It must be specific enough to distinguish from other skills.

Good: `Project conventions for this FastAPI + async SQLAlchemy API. Use when creating endpoints, models, schemas, or services.`

Bad: `Helps with API development.`

## When to add scripts

- Operation is deterministic (validation, formatting, code generation)
- Same code would be generated repeatedly
- Scripts save tokens vs generating the same code each time

## When to split into references

- SKILL.md exceeds 150 lines
- Content has distinct subtopics (e.g., migrations vs schema design)
- Some content is only needed occasionally

## Review checklist

- [ ] Description includes "Use when..." triggers
- [ ] SKILL.md ≤150 lines
- [ ] Each reference file ≤200 lines
- [ ] No generic best-practices the model already knows
- [ ] Encodes project-specific decisions, not textbook knowledge
- [ ] Concrete examples from the actual codebase
