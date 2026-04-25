# Ubiquitous Language

## Organization & Ownership

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Org Unit** | A node in the organizational hierarchy (company, division, team, etc.) with an optional parent. | Organization, team, department, group, dimension |
| **App** | A web application whose accessibility is tracked, owned by an **Org Unit**. | Property, site, project, product |
| **Slug** | A unique, URL-friendly identifier for an **App**, derived from the `name` field in the axe DevTools JSON at **Ingest** or **Import** time. | Key, code, handle |
| **Brand** | A commercial brand (Humana, CenterWell, Go365, CarePlus, Reliance) that owns one or more **Apps**, stored as a first-class entity with its own table. | Label, product line |

## Scanning & Ingestion

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Scan Run** | A single test execution across one or more pages of an **App**. The timestamp reflects when the scan was performed (from test data), not when it was uploaded. | Test run, scan, batch, execution, report |
| **Scan Run Status** | The lifecycle state of a **Scan Run**: **Pending** (accepting **Page Results**) or **Completed** (finalized, triggers scoring). Only the forward transition Pending → Completed is valid. | State, phase, stage |
| **Page Result** | The outcome of scanning a single URL within a **Scan Run**, including raw JSON, health category, and summary counts. | Page scan, page report, test result |
| **Raw JSON** | The full axe DevTools JSON payload preserved as JSONB on a **Page Result** for reprocessing and debugging. | Payload, source data |
| **Ingest** | A CLI operation that uploads a single scan directory as a **Scan Run** to an existing **App**, resolving the **App** by the JSON `name` field. | Upload, push |
| **Import** | A CLI operation that onboards an **App** along with its historical scan directories, creating the **App** from the JSON `name` field if it doesn't exist. Each `YYYY-MM-DD/` subdirectory becomes a **Scan Run**. | Bulk Import, batch upload, mass import |

## Findings & Rules

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Rule Finding** | A single axe rule outcome (violation or incomplete) for a **Page Result**, with severity, classification, and WCAG metadata. The **Impact** reflects the worst across its **Node Findings**. | Issue, rule result, defect, result |
| **Finding Type** | Whether a **Rule Finding** is a **Violation** (definite failure, counts toward scoring) or **Incomplete** (needs manual review, excluded from scoring). | Result type, finding kind |
| **Node Finding** | A specific DOM element instance that triggered a **Rule Finding**, with HTML snippet, selector, and failure details. | Instance, node result, occurrence, element |
| **Impact** | The severity of a **Rule Finding**: critical, serious, moderate, or minor. | Severity, priority, level |
| **Classification** | A standard that a **Rule Finding** belongs to — either a WCAG version/level pair (e.g., WCAG 2.1 AA) or best-practice. | Standard, conformance, tag |
| **Category** | The functional grouping of a **Rule Finding** (e.g., text-alternatives, keyboard, color) derived from the `cat.*` axe tag. | Group, type, area |
| **WCAG Criteria** | The WCAG success criteria a **Rule Finding** maps to — zero or more per finding (e.g., [1.1.1], [1.4.3, 1.4.6]). Stored as a JSONB array. | Rule, guideline, requirement |
| **Incomplete** | A **Rule Finding** that axe could not determine automatically, flagged for manual review and excluded from scoring. | Needs review, manual check, undetermined |
| **Pass** | An axe rule that all tested nodes satisfied. Preserved in the **Raw JSON** but not used in scoring or stored as **Rule Findings**. | Passed rule, success |
| **Inapplicable** | An axe rule that did not apply to any nodes on the page. Preserved in the **Raw JSON** but not used in scoring or stored as **Rule Findings**. | Not applicable, skipped, N/A |

## Scoring & Metrics

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Page Health** | A derived category for a **Page Result** based on its worst violation **Impact**. Uses distinct names to separate the health judgment from the raw impact level: Critical (has critical violations), Serious (worst is serious), Fair (worst is moderate), Good (worst is minor or no violations). | Page grade, page status, page score |
| **Score** | A weighted percentage computed from **Page Health** categories, where each page contributes by its health weight: Critical = 0, Serious = 0.4, Fair = 0.8, Good = 1.0. Formula: `(0×critical + 0.4×serious + 0.8×fair + 1.0×good) / total_pages`. | Rating, grade, index |
| **Score Snapshot** | A denormalized record of a **Score** and associated metrics (total violations, per-page averages, etc.) at a point in time for an **App**, **Org Unit**, or **Brand**. The `snapshot_at` field records **observation time** — for an **App**, the **Scan Run**'s `scanned_at`; for a rollup, the newest `snapshot_at` among the children it aggregates. | Score record, metric snapshot, data point |
| **Rollup** | The recomputation of aggregate scores as the arithmetic mean of children's latest **Score Snapshots**. Two forms: **Org Unit Rollup** (hierarchical, cascades up the tree) and **Brand Rollup** (flat, aggregates all **Apps** for a **Brand**). Triggered by any event that changes an **App**'s latest **Score Snapshot**: **Scan Run** completion, **Scan Run** deletion, **App** deletion, **App** reassignment to a different **Org Unit**, or **Org Unit** reparenting. | Aggregation, roll-up, propagation |
| **Brand Rollup** | A flat aggregation of the latest **Score Snapshots** across all **Apps** belonging to a **Brand**, regardless of **Org Unit** placement. Does not cascade. | Brand aggregation, brand scoring |

## Relationships

- An **Org Unit** has zero or one parent **Org Unit** and zero or more child **Org Units**
- An **Org Unit** owns zero or more **Apps**
- A **Brand** has zero or more **Apps**
- An **App** has exactly one **Brand** and one **Slug** (immutable after creation)
- An **App** has zero or more **Scan Runs**
- A **Scan Run** has exactly one **Scan Run Status** (Pending → Completed) and one or more **Page Results**
- A **Page Result** has zero or more **Rule Findings** and exactly one **Page Health**
- A **Rule Finding** has exactly one **Finding Type** (Violation or Incomplete), zero or more **Node Findings** (in practice, violations always have at least one), one or more **Classifications**, and zero or more **WCAG Criteria**
- A **Score Snapshot** belongs to an **App** (linked to a **Scan Run**), an **Org Unit** (recomputed via **Rollup**), or a **Brand** (recomputed via **Brand Rollup**)

## Example dialogue

> **Builder:** "Walk me through the ingestion flow — what happens when we upload scan data?"
>
> **Specifier:** "A **Scan Run** is created in **Pending** status. While it's **Pending**, you add **Page Results** — each one parses the **Raw JSON** and stores **Rule Findings** with their **Finding Type** (either **Violation** or **Incomplete**). Then you transition the **Scan Run Status** to **Completed**."
>
> **Builder:** "What triggers scoring?"
>
> **Specifier:** "The transition to **Completed**. Each **Page Result** gets a **Page Health** based on the worst **Impact** among its **Violation**-type **Rule Findings**. Then the **Score** is computed from those **Page Health** categories and saved as a **Score Snapshot**."
>
> **Builder:** "So **Incompletes** don't affect the **Score** at all?"
>
> **Specifier:** "Correct. **Incompletes** are stored for manual review but excluded from **Page Health** and **Score** computation. Only **Violations** count — and all of them, regardless of **Classification**. A best-practice **Violation** affects the **Score** just like a WCAG one."
>
> **Builder:** "And the **Rollup** happens automatically after that?"
>
> **Specifier:** "Yes. Once the app's **Score Snapshot** is saved, two rollups fire. The **Org Unit Rollup** cascades up the hierarchy — each ancestor **Org Unit** recomputes its **Score Snapshot** as the mean of its children's latest snapshots. The **Brand Rollup** aggregates the latest snapshots across all **Apps** for that **Brand**, regardless of where they sit in the **Org Unit** tree."
>
> **Builder:** "So **Brand Rollup** is flat — no cascading?"
>
> **Specifier:** "Exactly. A **Brand** doesn't have a hierarchy. It's a single aggregation across all **Apps** that share that **Brand**. Moving an **App** between **Org Units** changes the **Org Unit Rollup** but not the **Brand Rollup**."
>
> **Builder:** "What about **Import** — does that follow the same flow?"
>
> **Specifier:** "Exactly the same. **Import** just automates it — it creates the **App** from the JSON `name` if needed, then uploads each date subdirectory as a separate **Scan Run** through the same Pending → Completed lifecycle."

## Flagged ambiguities

- **"Issue"** was used informally to mean both a **Rule Finding** (a rule that failed) and a **Node Finding** (a specific DOM element). Avoid "issue" entirely in code — use **Violation** when counting failures that affect scoring (the former `issues_count` fields are being renamed to `violation_count` in #18). Use **Rule Finding** for the general concept and **Node Finding** for a specific element instance.
- **"Score"** can refer to both the computed percentage (the **Score** value) and the full **Score Snapshot** record. Use **Score** for the percentage and **Score Snapshot** for the persisted record with all metrics.
- **"Page"** was used to mean both a URL being tested and the **Page Result** record. Use **Page Result** when referring to the stored data. "Page" is acceptable in compound metrics like "pages with issues" where the meaning is clear.
- **"Severity"** and **"Impact"** were used interchangeably. The canonical term is **Impact**, matching axe's own terminology.
- **"Rollup"** now covers two distinct patterns: hierarchical cascading (**Org Unit Rollup**) and flat aggregation (**Brand Rollup**). When unqualified, "rollup" means the general concept. Use **Org Unit Rollup** or **Brand Rollup** when the distinction matters.
- **"Status"** is overloaded — **Scan Run Status** (Pending/Completed) vs. the health check endpoint's `"healthy"` status. Context usually disambiguates, but prefer **Scan Run Status** when referring to the lifecycle.
