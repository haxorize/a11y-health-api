# Feature Spec Template

Use this template when writing the GitHub issue body.

```markdown
## Problem Statement

The problem the user is facing, from the user's perspective.

## Solution

The solution to the problem, from the user's perspective.

## Acceptance Criteria

A numbered list of acceptance criteria. Each criterion should be in given/when/then format:

1. Given [context], when [action], then [expected outcome]

Example:
1. Given a scan request with a valid URL, when the scan completes, then results are stored with WCAG violation details

This list should be extensive and cover all aspects of the feature, including edge cases and error conditions.

## Implementation Decisions

A list of implementation decisions that were made, including:

- Modules to build or modify
- Interface changes
- Technical clarifications
- Architectural decisions
- Schema changes
- API contracts
- Specific interactions between components

Do NOT include specific file paths or code snippets — they become outdated quickly.

## Testing Decisions

Which modules will be tested and any feature-specific testing considerations (e.g., fixtures needed, external service mocks). Reference the `testing` skill for project test conventions.

## Out of Scope

What is explicitly not part of this feature.
```
