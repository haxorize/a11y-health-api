---
name: grill-me
description: Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Use when user wants to stress-test a plan, get grilled on their design, or mentions "grill me".
---

Interview me relentlessly about every aspect of this plan until we reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time.

If a question can be answered by exploring the codebase, explore the codebase instead.

## During the session

- **Sharpen fuzzy language inline.** When the user uses a vague or overloaded term, propose the canonical name from `UBIQUITOUS_LANGUAGE.md`. "You said 'snapshot' — do you mean a `ScoreSnapshot` or the rollup output?"
- **Cross-reference the glossary.** If the user's usage of a term conflicts with its definition in `UBIQUITOUS_LANGUAGE.md`, surface the mismatch immediately so the team language stays coherent.
- **Stress-test with concrete scenarios.** When domain relationships come up, invent specific edge cases that probe the boundaries. "What happens if an App moves between Org Units mid-Scan Run?" forces precision that abstract questions don't.
