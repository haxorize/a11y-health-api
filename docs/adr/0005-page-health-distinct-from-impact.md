# Page Health uses distinct names from axe Impact

A Page Result has a derived `page_health` that classifies the page based on its
worst violation Impact. The two vocabularies are deliberately different:

- **Impact** (axe's per-rule severity): `critical | serious | moderate | minor`
- **Page Health** (our derived per-page category): `Critical | Serious | Fair | Good`

`Critical` and `Serious` deliberately collide; `moderate` maps to `Fair`, and
`minor` (or no violations) maps to `Good`.

Considered and rejected:
- **Reuse axe's impact names verbatim**: the obvious choice, but conflates two
  different concepts. "This page is moderate" reads like a per-rule judgment,
  not a holistic page grade. The collision would also make scoring weights
  ambiguous in conversation ("does 'moderate' mean the rule or the page?").

The vocabulary split costs one extra term but keeps the model legible in code,
docs, and conversation. The mapping lives in scoring functions; renames here
ripple to API responses and the glossary, so revisit only with consumer
coordination.
