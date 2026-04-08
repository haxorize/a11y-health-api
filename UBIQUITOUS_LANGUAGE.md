# Ubiquitous Language

## Organization & Ownership

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Org Unit** | A node in the organizational hierarchy (company, division, team, etc.) with an optional parent. | Organization, team, department, group, dimension |
| **App** | A web application whose accessibility is tracked, owned by an **Org Unit**. | Property, site, project, product |
| **Slug** | A unique, URL-friendly identifier for an **App** that matches the directory name in the test results repo. | Key, code, handle |
| **Brand** | A static commercial brand (Humana, CenterWell, Go365, CarePlus, Reliance) assigned to an **App**. | Label, product line |

## Scanning & Ingestion

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Scan Run** | A single test execution across one or more pages of an **App**. The timestamp reflects when the scan was performed (from test data), not when it was uploaded. | Test run, scan, batch, execution, report |
| **Page Result** | The outcome of scanning a single URL within a **Scan Run**, including raw JSON, health category, and summary counts. | Page scan, page report, test result |
| **Raw JSON** | The full axe DevTools JSON payload preserved as JSONB on a **Page Result** for reprocessing and debugging. | Payload, source data |

## Findings & Rules

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Rule Finding** | A single axe rule outcome (violation or incomplete) for a **Page Result**, with severity, classification, and WCAG metadata. The **Impact** reflects the worst across its **Node Findings**. | Issue, rule result, defect, result |
| **Node Finding** | A specific DOM element instance that triggered a **Rule Finding**, with HTML snippet, selector, and failure details. | Instance, node result, occurrence, element |
| **Impact** | The severity of a **Rule Finding**: critical, serious, moderate, or minor. | Severity, priority, level |
| **Classification** | A standard that a **Rule Finding** belongs to — either a WCAG version/level pair (e.g., WCAG 2.1 AA) or best-practice. | Standard, conformance, tag |
| **Category** | The functional grouping of a **Rule Finding** (e.g., text-alternatives, keyboard, color) derived from the `cat.*` axe tag. | Group, type, area |
| **WCAG Criterion** | The specific WCAG success criterion a **Rule Finding** maps to (e.g., 1.1.1, 2.4.4). | Rule, guideline, requirement |
| **Incomplete** | A **Rule Finding** that axe could not determine automatically, flagged for manual review and excluded from scoring. | Needs review, manual check, undetermined |

## Scoring & Metrics

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Page Health** | A derived category for a **Page Result** based on its worst violation **Impact**. Uses distinct names to separate the health judgment from the raw impact level: Critical (has critical violations), Serious (worst is serious), Fair (worst is moderate), Good (worst is minor or no violations). | Page grade, page status, page score |
| **Score** | A weighted percentage computed from **Page Health** categories, where each page contributes by its health weight: Critical = 0, Serious = 0.4, Fair = 0.8, Good = 1.0. Formula: `(0×critical + 0.4×serious + 0.8×fair + 1.0×good) / total_pages`. | Rating, grade, index |
| **Score Snapshot** | A denormalized record of a **Score** and associated metrics (total issues, per-page averages, etc.) at a point in time for an **App** or **Org Unit**. | Score record, metric snapshot, data point |
| **Rollup** | The upward-cascading recomputation of **Org Unit** scores as the arithmetic mean of their direct children's latest **Score Snapshots**, triggered when an **App** score changes. | Aggregation, roll-up, propagation |

## Relationships

- An **Org Unit** has zero or one parent **Org Unit** and zero or more child **Org Units**
- An **Org Unit** owns zero or more **Apps**
- An **App** has exactly one **Brand** and one **Slug**
- An **App** has zero or more **Scan Runs**
- A **Scan Run** has one or more **Page Results**
- A **Page Result** has zero or more **Rule Findings** (violations and incompletes only) and exactly one **Page Health**
- A **Rule Finding** has zero or more **Node Findings** (in practice, violations always have at least one) and one or more **Classifications**
- A **Score Snapshot** belongs to either an **App** (linked to a **Scan Run**) or an **Org Unit** (recomputed via **Rollup**)

## Example dialogue

> **Builder:** "When a **Scan Run** is marked completed, do we compute **Page Health** for every **Page Result** at once?"
>
> **Specifier:** "Yes — on completion, each **Page Result** gets a **Page Health** based on the worst **Impact** among its **Rule Findings**. Then the **Score** is computed from those **Page Health** categories."
>
> **Builder:** "What about **Incompletes** — do they affect **Page Health**?"
>
> **Specifier:** "No. **Incompletes** are stored as **Rule Findings** for manual review but excluded from **Page Health** and **Score** computation. Only violations count."
>
> **Builder:** "And if a violation is a best-practice rather than WCAG — does it still affect the **Score**?"
>
> **Specifier:** "Yes. Best-practice is just a **Classification**. All violations count toward **Page Health** based on their **Impact**, regardless of **Classification**."
>
> **Builder:** "Once the app **Score Snapshot** is saved, the **Rollup** kicks in for ancestor **Org Units**?"
>
> **Specifier:** "Exactly. Each ancestor's **Score Snapshot** is recomputed as the mean of its children's latest snapshots, cascading up to the root **Org Unit**."

## Flagged ambiguities

- **"Issue"** was used informally throughout the conversation to mean both a **Rule Finding** (a rule that failed) and a **Node Finding** (a specific DOM element). In this domain, "issue" should refer to a **Rule Finding**. Use **Node Finding** when referring to a specific element instance.
- **"Score"** can refer to both the computed percentage (the **Score** value) and the full **Score Snapshot** record. Use **Score** for the percentage and **Score Snapshot** for the persisted record with all metrics.
- **"Page"** was used to mean both a URL being tested and the **Page Result** record. Use **Page Result** when referring to the stored data. "Page" is acceptable in compound metrics like "pages with issues" where the meaning is clear.
- **"Severity"** and **"Impact"** were used interchangeably. The canonical term is **Impact**, matching axe's own terminology.
