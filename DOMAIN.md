# Ubiquitous Language

## Organization & Ownership

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Org Unit** | A node in the organizational hierarchy (company, division, team, etc.) with an optional parent. | Organization, team, department, group, dimension |
| **Root Org Unit** | The single parentless **Org Unit** at the apex of the hierarchy — the subject of portfolio-level views. The hierarchy is a tree, not a forest: a deployment has at most one (zero only before onboarding), and creating or reparenting a second parentless **Org Unit** is refused (`duplicate_root`, 409). | Root, top-level org, portfolio org, primary org |
| **App** | A web application whose accessibility is tracked, owned by an **Org Unit**. | Property, site, project, product |
| **Slug** | A unique, URL-friendly identifier for an **App**, derived server-side from the name at **App** creation — folded to lowercase ASCII with words joined by hyphens — never chosen by an operator and immutable thereafter. Distinct names that derive to the same **Slug** collide loudly at creation rather than silently sharing an **App**. | Key, code, handle |
| **Brand** | A commercial brand (Humana, CenterWell, Go365, CarePlus, Reliance) that owns one or more **Apps**, stored as a first-class entity with its own table. | Label, product line |

## Scanning & Ingestion

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Scan Run** | A single test execution across one or more pages of an **App**. The timestamp reflects when the scan was performed (from test data), not when it was uploaded. | Test run, scan, batch, execution, report |
| **Scan Run Status** | The lifecycle state of a **Scan Run**: **Pending** (accepting **Page Results**) or **Completed** (finalized, triggers scoring). Only the forward transition Pending → Completed is valid, and only once the run has at least one **Page Result** — an empty run refuses completion (`empty_scan_run`, 409) rather than scoring "no data" as zero. | State, phase, stage |
| **Page Result** | The outcome of scanning a single URL within a **Scan Run**, including raw JSON, health category, and summary counts. | Page scan, page report, test result |
| **Raw JSON** | The full axe DevTools JSON preserved as JSONB on a **Page Result** for reprocessing and debugging — stored exactly as uploaded (including fields the ingestion schema doesn't model) and never rewritten or re-serialized. | Payload (unqualified), source data |
| **Axe Payload** | The axe DevTools JSON document uploaded for one page, validated at the ingest boundary by the `AxePayload` schema. A well-formed request whose axe payload fails that validation is the `invalid_axe_payload` error mode (400). Say **Axe Payload** for the document being validated, **Raw JSON** for the preserved copy; "payload" alone stays banned. | Payload (unqualified), upload, scan JSON |
| **Ingest** | A CLI operation that uploads a single scan directory as a **Scan Run** to an existing **App**, resolving the **App** by the **Slug** derived from the JSON `name` field — so presentation-only variants that share a **Slug** resolve to one **App**. | Upload, push |
| **Import** | A CLI operation that onboards an **App** along with its historical scan directories, resolving (and creating if absent) the **App** by the **Slug** derived from the JSON `name` field. Across scans whose names share a **Slug** but differ in presentation, the newest by observation time supplies the display name; a genuine conflict is two or more distinct **Slugs**. An operator-supplied display name may stand in for the JSON `name` at creation only when it derives to the same **Slug**; against an existing **App** it is ignored with a warning. Each `YYYY-MM-DD/` subdirectory becomes a **Scan Run**. | Bulk Import, batch upload, mass import |

## Findings & Rules

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Rule Finding** | A single axe rule outcome (violation or incomplete) for a **Page Result**, with severity, classification, and WCAG metadata. The **Impact** reflects the worst across its **Node Findings**. | Issue, rule result, defect, result |
| **Finding Type** | Whether a **Rule Finding** is a **Violation** (definite failure, counts toward scoring) or **Incomplete** (needs manual review, excluded from scoring). | Result type, finding kind |
| **Node Finding** | A specific DOM element instance that triggered a **Rule Finding**, with HTML snippet, selector, and failure details. | Instance, node result, occurrence, element |
| **Impact** | The severity of a **Rule Finding**: critical, serious, moderate, or minor. | Severity, priority, level |
| **Classification** | A standard that a **Rule Finding** belongs to — either a WCAG version/level pair (levels A, AA, or AAA — e.g., WCAG 2.1 AA, WCAG 2.2 AAA) or best-practice. | Standard, conformance, tag |
| **Category** | The functional grouping of a **Rule Finding** (e.g., text-alternatives, keyboard, color) derived from the `cat.*` axe tag. | Group, type, area |
| **WCAG Criteria** | The WCAG success criteria a **Rule Finding** maps to — zero or more per finding (e.g., [1.1.1], [1.4.3, 1.4.6]). Stored as a JSONB array. | Rule, guideline, requirement |
| **Incomplete** | A **Rule Finding** that axe could not determine automatically, flagged for manual review and excluded from scoring. | Needs review, manual check, undetermined |
| **Pass** | An axe rule that all tested nodes satisfied. Preserved in the **Raw JSON** but not used in scoring or stored as **Rule Findings**. | Passed rule, success |
| **Inapplicable** | An axe rule that did not apply to any nodes on the page. Preserved in the **Raw JSON** but not used in scoring or stored as **Rule Findings**. | Not applicable, skipped, N/A |

## Scoring & Metrics

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Page Health** | A derived category for a **Page Result** based on its worst violation **Impact**. Uses distinct names to separate the health judgment from the raw impact level: Critical (has critical violations), Serious (worst is serious), Fair (worst is moderate), Good (worst is minor or no violations). | Page grade, page status, page score |
| **Score** | A weighted average computed from **Page Health** categories, where each page contributes by its health weight: Critical = 0, Serious = 0.4, Fair = 0.8, Good = 1.0. Formula: `(0×critical + 0.4×serious + 0.8×fair + 1.0×good) / total_pages`. The wire scale is a 0–1 fraction, not a percentage; the UI presents it as a 0–100 integer. | Rating, grade, index, percentage |
| **Score Snapshot** | A denormalized record of a **Score** and the raw counts it summarizes (total pages, total violations, pages with violations, pages with critical violations) at a point in time for an **App**, **Org Unit**, or **Brand**. Carries no derived per-page shares or averages — consumers derive those from the counts. The `snapshot_at` field records **observation time** — for an **App**, the **Scan Run**'s `scanned_at`; for a rollup, the newest `snapshot_at` among the children it aggregates. | Score record, metric snapshot, data point |
| **Latest Score Snapshot** | The most recent **Score Snapshot** for one owner (**App**, **Org Unit**, or **Brand**), ordered by `snapshot_at` (observation time) with ties broken by highest id — *not* by insertion order, so a historical **Import** never displaces a newer observation. The value **Rollups** aggregate and `/scores/latest` serves; both select it through one shared definition. | Current score, newest snapshot, last score |
| **Rollup** | The recomputation of aggregate scores as the arithmetic mean of children's latest **Score Snapshots**. Two forms: **Org Unit Rollup** (hierarchical, cascades up the tree) and **Brand Rollup** (flat, aggregates all **Apps** for a **Brand**). Triggered by any event that changes an **App**'s latest **Score Snapshot**: **Scan Run** completion, **Scan Run** deletion, **App** deletion, **App** reassignment to a different **Org Unit**, or **Org Unit** reparenting. | Aggregation, roll-up, propagation |
| **Brand Rollup** | A flat aggregation of the latest **Score Snapshots** across all **Apps** belonging to a **Brand**, regardless of **Org Unit** placement. Does not cascade. | Brand aggregation, brand scoring |
| **Scoring Vocabulary** | The declared meaning behind the scoring value sets: the **Page Health** ordering (worst → best, each health's rank derived from its position), each health's weight in the **Score**, and the total **Impact** → **Page Health** mapping (every **Impact** maps explicitly, including minor → Good). One module is its single source — the scoring engine imports it, and a read-only endpoint serves the deployed server's vocabulary so no client re-derives or hard-codes it. | Scoring config, weight table, severity map, scoring constants |

## API Contract

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Error Contract** | The declared set of error modes each API operation can produce — a mode being one domain exception type mapped to a status code and **Error Code** — derived from a single table so runtime behavior, handler registration, and the OpenAPI document cannot drift apart. The human-readable message comes from the raising exception, not the table. Request-shape violations use the framework's standard 422; well-formed requests that fail domain validation return 400 with a coded body. Messages are end-user-safe by convention: the UI renders them verbatim in production (its ADR 0010), so write them for the person seeing the error screen — never internals like stack traces, SQL, file paths, or config values. | Error handling, error mapping, exception mapping |
| **Error Code** | A machine-readable identifier for one domain error mode, drawn from a closed vocabulary declared in the **Error Contract** (exactly one code per mode). The UI narrows on it instead of parsing message text. | Error type, error name, reason code |
| **Declaration Honesty** | The suite-wide invariant that any non-framework 4xx observed during tests must be declared on the operation that produced it, with its **Error Code** among the operation's declared codes. Enforced by an ASGI shim wrapping the test clients, so an undeclared mode fails the suite instead of surviving review. | Honesty check, contract check |
| **Existence Guard** | The single check that a referenced entity exists before an operation proceeds, raising the not-found error mode from one module with a label from its one closed table — so an absent **App**, **Brand**, **Org Unit**, **Scan Run**, **Rule Finding**, or **Score Snapshot** (labeled as its **Scan Run**'s summary) always fails the same way, and no service imports another service just to ask "does it exist?" (or to fetch an entity it only reads). | Get-or-404, existence check, lookup guard |
| **Integrity Guard** | The single mechanism that turns a database constraint violation into the **Error Contract**: a guarded write declares which constraints it defends and the domain error each one raises; a recognized violation raises that error with the transaction still usable, and any unrecognized violation propagates unchanged. Backs the **Root Org Unit** invariant, **Slug** uniqueness, and the **Dependents Guard**. | Guarded flush, constraint guard, savepoint guard, integrity translation |
| **Dependents Guard** | The rule that an **Org Unit** with dependent records — child **Org Units**, **Apps**, or **Score Snapshots** — refuses deletion with the `has_dependents` error mode (409). The database RESTRICT constraints are the source of truth; the **Integrity Guard** translates a violation into the error mode the service declares. Contrast with **App** deletion, which cascades to the **App**'s **Scan Runs** and **Score Snapshots** instead of refusing. | Delete guard, dependency check, referential guard |
| **Cursor Pagination** | The contract for every unbounded list operation: results arrive as a page of items plus a `next_cursor`, paging is forward-only, the page size is bounded with a shared default, and direction is ascending unless the operation bakes another server-side or exposes **Sort Order**. One pagination-owned definition supplies the request parameters to every such operation, and any operation that serves a page of results must accept a **Cursor** and declare the `invalid_cursor` error mode — enforced suite-wide in both directions (accepting a **Cursor** implies serving the paginated envelope), like **Declaration Honesty**. Bounded reference lists deliberately return bare arrays instead. | Offset pagination, page number, skip/take, limit/offset |
| **Cursor** | The opaque continuation token marking the position after the last returned row of **Cursor Pagination**; a client sends it back verbatim to fetch the next page and never inspects or constructs one. A cursor that cannot be decoded is the `invalid_cursor` error mode (400). | Page token, offset, bookmark |
| **Sort Order** | The client-chosen direction of a **Cursor Pagination** walk — `asc` (oldest first, the default) or `desc` (newest first) — exposed as the `order` query parameter only on operations where both directions have real consumers. `order`/`asc`/`desc` is the wire vocabulary; the service seam names the same choice `descending`. | Sort direction, ordering, order-by, direction flag |

## Relationships

- An **Org Unit** has zero or one parent **Org Unit** and zero or more child **Org Units**; at most one **Org Unit** is parentless (the **Root Org Unit**)
- An **Org Unit** owns zero or more **Apps**
- A **Brand** has zero or more **Apps**
- An **App** has exactly one **Brand** and one **Slug** (name and **Slug** immutable after creation)
- An **App** has zero or more **Scan Runs**
- A **Scan Run** has exactly one **Scan Run Status** (Pending → Completed) and one or more **Page Results**
- A **Page Result** has zero or more **Rule Findings** and exactly one **Page Health**
- A **Rule Finding** has exactly one **Finding Type** (Violation or Incomplete), zero or more **Node Findings** (in practice, violations always have at least one), one or more **Classifications**, and zero or more **WCAG Criteria**
- A **Score Snapshot** belongs to an **App** (linked to a **Scan Run**), an **Org Unit** (recomputed via **Rollup**), or a **Brand** (recomputed via **Brand Rollup**)
- Deleting an **App** cascades to its **Scan Runs** and **Score Snapshots**; deleting an **Org Unit** that has dependents is refused (**Dependents Guard**)

## Example dialogue

> **Dev:** "Walk me through the ingestion flow — what happens when we upload scan data?"
>
> **Domain expert:** "A **Scan Run** is created in **Pending** status. While it's **Pending**, you add **Page Results** — each one parses the **Raw JSON** and stores **Rule Findings** with their **Finding Type** (either **Violation** or **Incomplete**). Then you transition the **Scan Run Status** to **Completed**."
>
> **Dev:** "What triggers scoring?"
>
> **Domain expert:** "The transition to **Completed**. Each **Page Result** gets a **Page Health** based on the worst **Impact** among its **Violation**-type **Rule Findings**. Then the **Score** is computed from those **Page Health** categories and saved as a **Score Snapshot**."
>
> **Dev:** "So **Incompletes** don't affect the **Score** at all?"
>
> **Domain expert:** "Correct. **Incompletes** are stored for manual review but excluded from **Page Health** and **Score** computation. Only **Violations** count — and all of them, regardless of **Classification**. A best-practice **Violation** affects the **Score** just like a WCAG one."
>
> **Dev:** "And the **Rollup** happens automatically after that?"
>
> **Domain expert:** "Yes. Once the app's **Score Snapshot** is saved, two rollups fire. The **Org Unit Rollup** cascades up the hierarchy — each ancestor **Org Unit** recomputes its **Score Snapshot** as the mean of its children's latest snapshots. The **Brand Rollup** aggregates the latest snapshots across all **Apps** for that **Brand**, regardless of where they sit in the **Org Unit** tree."
>
> **Dev:** "So **Brand Rollup** is flat — no cascading?"
>
> **Domain expert:** "Exactly. A **Brand** doesn't have a hierarchy. It's a single aggregation across all **Apps** that share that **Brand**. Moving an **App** between **Org Units** changes the **Org Unit Rollup** but not the **Brand Rollup**."
>
> **Dev:** "What about **Import** — does that follow the same flow?"
>
> **Domain expert:** "Exactly the same. **Import** just automates it — it creates the **App** from the JSON `name` if needed, then uploads each date subdirectory as a separate **Scan Run** through the same Pending → Completed lifecycle."

## Flagged ambiguities

- **"Issue"** was used informally to mean both a **Rule Finding** (a rule that failed) and a **Node Finding** (a specific DOM element). Avoid "issue" entirely in code — use **Violation** when counting failures that affect scoring (the former `issues_count` fields are being renamed to `violation_count` in #18). Use **Rule Finding** for the general concept and **Node Finding** for a specific element instance.
- **"Score"** can refer to both the computed value and the full **Score Snapshot** record. Use **Score** for the 0–1 value and **Score Snapshot** for the persisted record with its counts.
- **"Page"** carries three senses: a URL being tested, the **Page Result** record, and a page of list results in **Cursor Pagination** (the API's `Page` envelope). Use **Page Result** for the stored data and "page of results" when talking about pagination. "Page" is acceptable in compound metrics like "pages with issues" where the meaning is clear.
- **"Severity"** and **"Impact"** were used interchangeably. The canonical term is **Impact**, matching axe's own terminology.
- **"Rollup"** now covers two distinct patterns: hierarchical cascading (**Org Unit Rollup**) and flat aggregation (**Brand Rollup**). When unqualified, "rollup" means the general concept. Use **Org Unit Rollup** or **Brand Rollup** when the distinction matters.
- **"Status"** is overloaded — **Scan Run Status** (Pending/Completed) vs. the health check endpoint's `"healthy"` status. Context usually disambiguates, but prefer **Scan Run Status** when referring to the lifecycle.

## Cross-repo

The UI consumes these terms via the generated client. See `../a11y-health-ui/DOMAIN.md` for any UI-only conventions.
