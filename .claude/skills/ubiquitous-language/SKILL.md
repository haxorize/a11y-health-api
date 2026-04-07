---
name: ubiquitous-language
description: Extract a DDD-style ubiquitous language glossary from the current conversation and codebase, flagging ambiguities and proposing canonical terms. Saves to UBIQUITOUS_LANGUAGE.md. Use when user wants to define domain terms, build a glossary, harden terminology, create a ubiquitous language, or mentions "domain model" or "DDD".
---

# Ubiquitous Language

Extract and formalize domain terminology into a consistent glossary.

## Process

### 1. Scan for domain terms

- Scan the **conversation** for domain-relevant nouns, verbs, and concepts
- Scan the **codebase** — models, schemas, endpoint names, database columns, and variable names — for domain terms already in use

### 2. Identify problems

- Same word used for different concepts (ambiguity)
- Different words used for the same concept (synonyms)
- Vague or overloaded terms
- Mismatches between conversation terminology and codebase terminology

### 3. Propose a canonical glossary

Be opinionated — pick the best term for each concept and list alternatives as aliases to avoid.

### 4. Write to `UBIQUITOUS_LANGUAGE.md`

Write the glossary to `UBIQUITOUS_LANGUAGE.md` in the working directory using the format in [references/output-format.md](references/output-format.md).

### 5. Output a summary

Summarize the glossary inline in the conversation. Suggest: "Consider adding a reference to `UBIQUITOUS_LANGUAGE.md` in CLAUDE.md so future sessions use these terms consistently."

## Rules

- **Be opinionated.** Pick the best term; list others as aliases to avoid.
- **Flag conflicts explicitly** in the "Flagged ambiguities" section with a clear recommendation.
- **Only domain terms.** Skip module/class names unless they have domain meaning. Skip generic programming concepts unless they have domain-specific meaning.
- **Keep definitions tight.** One sentence max. Define what it IS, not what it does.
- **Show relationships** with bold term names and cardinality where obvious.
- **Group terms into tables** when natural clusters emerge (by subdomain, lifecycle, or actor). One table is fine if all terms belong to a single cohesive domain — don't force groupings.
- **Write an example dialogue** (3-5 exchanges) between a **Builder** and a **Specifier** that demonstrates how terms interact. The dialogue should clarify boundaries between related concepts.

## Re-running

When invoked again in the same conversation:

1. Read the existing `UBIQUITOUS_LANGUAGE.md`
2. Scan the conversation and codebase for new terms
3. Update definitions if understanding has evolved
4. Re-flag any new ambiguities
5. Update the example dialogue to incorporate new terms
