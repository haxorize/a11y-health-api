# Ubiquitous Language

## Organization & Ownership

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Org Unit** | A node in the organizational hierarchy (company, division, team, etc.) with an optional parent. | Organization, team, department, group, dimension |
| **Root Org Unit** | The single parentless **Org Unit** at the apex of the hierarchy, the subject of portfolio-level views. The hierarchy is a tree, not a forest: a deployment has at most one, and none before onboarding or once it is deleted, so creating or reparenting a second parentless **Org Unit** is refused. Reparents run one at a time, so the app never commits a cycle; a cycle written from outside the app is still possible, so walks over the hierarchy and the **Org Unit Rollup** stop at one. | Root, top-level org, portfolio org, primary org |
| **App** | A web application whose accessibility is tracked, owned by an **Org Unit**. | Property, site, project, product |
| **Slug** | A unique, URL-friendly identifier for an **App**, derived server-side from the name at creation and immutable thereafter. It is never chosen by an operator, and two distinct names that derive to the same **Slug** are refused at creation rather than silently sharing an **App**. | Key, code, handle |
| **Brand** | A commercial brand (Humana, CenterWell, Go365, CarePlus, Reliance) that owns one or more **Apps**. A **Brand** sits outside the **Org Unit** tree: it has no parent and no placement. | Label, product line |

## Scanning & Ingestion

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Scan Run** | A single test execution across one or more pages of an **App**. Its timestamp is when the scan was performed, taken from the test data, not when it was uploaded. | Test run, scan, batch, execution, report |
| **Scan Run Status** | The lifecycle state of a **Scan Run**: **Pending**, accepting **Page Results**, or **Completed**, finalized and scored. The only transition is Pending to Completed, and ADR 0044 settles what refuses it and why. Completing a run and adding a **Page Result** to it run one at a time, so a second completion is refused as an invalid transition and a page arriving mid-completion is refused because the run is **Completed**. | State, phase, stage |
| **Page Result** | The outcome of scanning a single URL within a **Scan Run**, including raw JSON, health category, and summary counts. | Page scan, page report, test result |
| **Raw JSON** | The full axe DevTools JSON preserved on a **Page Result** for reprocessing and debugging, stored exactly as uploaded (including fields the ingestion schema does not model) and never rewritten or re-serialized. | Payload (unqualified), source data |
| **Axe Payload** | The axe DevTools JSON document uploaded for one page, as validated at the **Axe Boundary**. Say **Axe Payload** for the document being validated and **Raw JSON** for the preserved copy; "payload" alone stays banned in prose and in any name not typed as this document. | Payload (unqualified), upload, scan JSON |
| **Axe Boundary** | The one validation crossing every axe DevTools document passes through, `parse_axe_payload`, turning uploaded JSON into an **Axe Payload** or refusing it. It runs in two places: at **Page Result** creation on the server, where a failing document is one refused request, and in the CLI at scan load, where every failing file in a **Scan Directory** is reported before any upload. This is the server-side sense of "ingest"; the CLI operation is **Ingest**. | Ingest boundary, validation crossing, parse step |
| **Scan Directory** | A directory of axe DevTools JSON files on an operator's disk, one page per file, before any upload exists. It is the unit **Ingest** consumes and the unit each dated subdirectory of an **Import** is. It is not yet a **Scan Run**: nothing is persisted and no **App** is resolved until it is uploaded, which is why the bare word "scan" stays banned for both. | Scan, scan folder, upload folder |
| **Ingest** | The CLI operation that uploads one **Scan Directory** as a **Scan Run** to an existing **App**. The **App** is resolved by the **Slug** derived from the JSON name, so presentation-only variants of a name resolve to one **App**. | Upload, push |
| **Import** | The CLI operation that onboards an **App** with its historical **Scan Directories**, one dated subdirectory per **Scan Run**, creating the **App** if absent. The **App** is resolved by the **Slug** derived from the JSON name; across scans whose names share a **Slug**, the newest by **Observation Time** supplies the display name, and two distinct **Slugs** are a conflict. An operator-supplied display name may stand in for the JSON name at creation only, and only when it derives to the same **Slug**. | Bulk Import, batch upload, mass import |

## Findings & Rules

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Rule Finding** | A single axe rule outcome (violation or incomplete) for a **Page Result**, with severity, classification, and WCAG metadata. The **Impact** reflects the worst across its **Node Findings**. | Issue, rule result, defect, result |
| **Finding Type** | Whether a **Rule Finding** is a **Violation** (definite failure, counts toward scoring) or **Incomplete** (needs manual review, excluded from scoring). | Result type, finding kind |
| **Violation** | A **Rule Finding** that is a definite failure and counts toward scoring. Every **Violation** counts, whether its **Classification** is WCAG or best-practice. | Issue, failure, error, defect |
| **Node Finding** | A specific DOM element instance that triggered a **Rule Finding**, with HTML snippet, selector, and failure details. | Instance, node result, occurrence, element |
| **Impact** | The severity of a **Rule Finding**: critical, serious, moderate, or minor. | Severity, priority, level |
| **Classification** | A standard that a **Rule Finding** belongs to: a WCAG version-and-level pair, such as WCAG 2.1 AA, or best-practice. A WCAG **Classification** carries a version and a level; a best-practice **Classification** carries neither. | Standard (the wire member naming the wcag-versus-best-practice axis, not the whole), conformance, tag |
| **Classification Token** | The compact token naming one **Classification**, such as wcag21aa or best-practice, and the findings filter's query vocabulary. The vocabulary is closed and each token maps to exactly one **Classification**, so the token map is also the one place a stored **Classification**'s shape comes from. | Tag, classification string |
| **Category** | The functional grouping of a **Rule Finding** (e.g., text-alternatives, keyboard, color) derived from the `cat.*` axe tag. | Group, type, area |
| **WCAG Criteria** | The WCAG success criteria a **Rule Finding** maps to, zero or more per finding (e.g., 1.1.1; 1.4.3 and 1.4.6). | Rule, guideline, requirement |
| **Incomplete** | A **Rule Finding** that axe could not determine automatically, flagged for manual review and excluded from scoring. | Needs review, manual check, undetermined |
| **Pass** | An axe rule that all tested nodes satisfied. Preserved in the **Raw JSON** but not used in scoring or stored as **Rule Findings**. | Passed rule, success |
| **Inapplicable** | An axe rule that did not apply to any nodes on the page. Preserved in the **Raw JSON** but not used in scoring or stored as **Rule Findings**. | Not applicable, skipped, N/A |

## Scoring & Metrics

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Page Health** | A derived category for a **Page Result** based on its worst violation **Impact**. Uses distinct names to separate the health judgment from the raw impact level: Critical (has critical violations), Serious (worst is serious), Fair (worst is moderate), Good (worst is minor or no violations). | Page grade, page status, page score |
| **Score** | How healthy one owner is, on one scale for all three: for an **App**, a weighted average over a **Scan Run**'s **Page Health** categories, each page contributing its health's weight, Critical 0, Serious 0.4, Fair 0.8, Good 1.0; for an **Org Unit** or a **Brand**, the **Score Aggregates** mean of the children's. The wire scale is a 0 to 1 fraction, not a percentage; the UI presents it as a 0 to 100 integer. The **Scoring Vocabulary** is the authority on the weights. | Rating, grade, index, percentage |
| **Observation Time** | The moment a **Score Snapshot** describes: the **Scan Run**'s scan time for an **App**, and the newest **Observation Time** among the children it aggregates for a rollup owner. The `snapshot_at` field records it. It is not insertion time, so a historical **Import** never displaces a newer observation. | Snapshot time, upload time, created time |
| **Score Snapshot** | A persisted record of the **Score Aggregates** for one **Owner** at one **Observation Time**. It carries no derived per-page shares or averages; consumers derive those from the counts. | Score record, metric snapshot, data point |
| **Score Aggregates** | The **Score** and the raw counts a **Score Snapshot** summarizes (total pages, total violations, pages with violations, pages with critical violations), as one immutable value with exactly one definition. **Observation Time** is time, not an aggregate, and stays outside the value. The **Rollup** arithmetic, the mean of the children's **Scores** and the sums of their counts, is a property of this value. | Aggregate values, metrics, snapshot values, the five fields |
| **Scan Run Summary** | A **Scan Run**'s **Score Aggregates**, read through the run rather than through its **App**'s **Score Snapshot**. It exists only once the run is **Completed**; a **Pending** run has none, and the **Existence Guard** names the missing record by this term. | Run score, run metrics, scan totals |
| **Owner** | The entity a **Score Snapshot** belongs to: an **App**, an **Org Unit**, or a **Brand**. **Org Units** and **Brands** are *rollup owners*, whose snapshots exist only via **Rollup**, and the **Owner** is the unit of snapshot uniqueness and of **Rollup** serialization. | Subject, holder, parent entity |
| **Owner Dispatcher** | The one module where per-**Owner** variation lives: the owner spec table and the snapshot construction, scope resolution, score reads, and **Rollup** machinery that consume it, including which rollup owners an **App** feeds. Its charter is closed: **App** score computation stays outside it, and no per-owner dispatch exists anywhere else. | Owner registry, dispatch table, owner map |
| **Latest Score Snapshot** | The most recent **Score Snapshot** for one **Owner**, by **Observation Time** with ties broken by highest id, never by insertion order. It is the value **Rollups** aggregate and the latest-scores listing serves, through one shared definition. | Current score, newest snapshot, last score |
| **Rollup** | The recomputation of an **Owner**'s **Score Aggregates** from its children's **Latest Score Snapshots**, in two forms: **Org Unit Rollup**, which cascades up the tree, and **Brand Rollup**, which is flat. It fires on any event that changes an **App**'s **Latest Score Snapshot**. Concurrent **Rollups** for one **Owner** run one at a time, and a **Rollup** that loses that ordering fails with a retryable conflict; these loss modes are the *rollup races*. | Aggregation, roll-up, propagation |
| **Org Unit Rollup** | The hierarchical **Rollup** of an **Org Unit** from its child **Org Units** and its own **Apps**, cascading to each ancestor in turn. Reparenting an **Org Unit** or moving an **App** re-runs it for the old and the new parent. | Hierarchy rollup, cascade, tree aggregation |
| **Brand Rollup** | A flat aggregation of the latest **Score Snapshots** across all **Apps** belonging to a **Brand**, regardless of **Org Unit** placement. Does not cascade. | Brand aggregation, brand scoring |
| **Scoring Vocabulary** | The declared meaning behind the scoring value sets: the **Page Health** ordering from worst to best, each health's weight in the **Score**, and the total **Impact** to **Page Health** mapping. One module is its single source, and a read-only endpoint serves the deployed server's vocabulary so no client re-derives or hard-codes it. | Scoring config, weight table, severity map, scoring constants |

## API Contract

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Error Contract** | The declared set of error modes each API operation can produce, a mode being one domain exception mapped to one status code and one **Error Code**, all derived from a single table. Request-shape violations use the framework's standard 422; a well-formed request that fails domain validation returns 400 with a coded body. ADR 0022 owns the table and the end-user-safe rule messages are written to. | Error handling, error mapping, exception mapping |
| **Error Code** | A machine-readable identifier for one domain error mode, drawn from a closed vocabulary declared in the **Error Contract** (exactly one code per mode). The UI narrows on it instead of parsing message text. | Error type, error name, reason code |
| **Declaration Honesty** | The suite-wide invariant that any non-framework 4xx observed during tests is declared on the operation that produced it, with its **Error Code** among the operation's declared codes. "Declared" means the operation's effective declaration, the same view the OpenAPI document is generated from. The one mode no endpoint test provokes organically, the *rollup races*' conflict — raised both by a deadlock and by the partial unique indexes that decide same-observation writes — is enforced at its raise site instead, in both directions. | Honesty check, contract check |
| **Existence Guard** | The single check that a referenced entity exists before an operation proceeds. One module builds the not-found mode, with a label from one closed table, and raises it on a miss; the **Integrity Guard** raises the same error when a write's reference is deleted after the check. Every entity fails the same way, and no service imports another service just to ask whether something exists. | Get-or-404, existence check, lookup guard |
| **Integrity Guard** | The single mechanism that turns a database constraint violation into the **Error Contract**: a guarded write declares which constraints it defends and the domain error each one raises. A recognized violation raises that error with the transaction still usable; an unrecognized violation propagates unchanged. | Guarded flush, constraint guard, savepoint guard, integrity translation |
| **Dependents Guard** | The rule that an **Org Unit** with dependent records (child **Org Units**, **Apps**, or **Score Snapshots**) refuses deletion. The database's RESTRICT constraints are the source of truth and the **Integrity Guard** translates the violation; contrast **App** deletion, which cascades to the **App**'s **Scan Runs** and **Score Snapshots** instead of refusing. | Delete guard, dependency check, referential guard |
| **Sibling-Import Rule** | The suite-wide invariant over one package's internal imports: which modules may import which of their siblings. In the services package every module sits in exactly one of two tables, checked against the package itself so none goes unclassified: an allowlist of the siblings each scoring module and shared helper may reach, and the resource services, which reach scoring only through the **Rollup** trigger module. It exists because package privacy alone lets every sibling import a shared private module, and this rule is the only thing holding that line. | Cross-module rule, crossing rule, import rules (unqualified) |
| **Cursor Pagination** | The contract for every unbounded list operation: results arrive as a page of items plus a next **Cursor**, paging is forward-only, the page size is bounded with a shared default, and direction is baked per-operation unless the operation exposes **Sort Order**. Any operation that serves a page must accept a **Cursor**, and any that accepts one must serve the page envelope, enforced suite-wide like **Declaration Honesty**. Bounded reference lists return bare arrays instead, and an operation whose consumers need an exact filtered count opts into the *totaled* envelope, the same page shape plus a total. | Offset pagination, page number, skip/take, limit/offset |
| **Cursor** | The opaque continuation token marking the position after the last returned row of **Cursor Pagination**. A client sends it back verbatim to fetch the next page and never inspects or constructs one; a cursor that cannot be decoded is refused. | Page token, offset, bookmark |
| **Sort Order** | The client-chosen direction of a **Cursor Pagination** walk: ascending, oldest first and the default, or descending, newest first. It is exposed only on operations where both directions have real consumers, and the service seam names the same choice `descending`. | Sort direction, ordering, order-by, direction flag |
| **Filter Options** | The server-enumerated distinct values present across one **Scan Run**'s **Rule Findings**, per filter dimension: **WCAG Criteria** in numeric order and **Classifications** in vocabulary order, each paired with the **Classification Token** that names it. A stored **Classification** the vocabulary cannot name earns no option, since the filter cannot query what it cannot name. "Dimension" here means a filter axis, never an **Org Unit**. | Facets, available filters, filter values |

## Relationships

- An **Org Unit** has zero or one parent **Org Unit** and zero or more child **Org Units**; at most one **Org Unit** is parentless (the **Root Org Unit**)
- An **Org Unit** owns zero or more **Apps**
- A **Brand** has zero or more **Apps**
- An **App** has exactly one **Brand** and one **Slug** (name and **Slug** immutable after creation)
- An **App** has zero or more **Scan Runs**
- A **Scan Run** has exactly one **Scan Run Status** (Pending → Completed), zero or more **Page Results** while Pending, and one or more once Completed
- A **Page Result** has zero or more **Rule Findings**, and exactly one **Page Health** once its **Scan Run** completes — none while the run is Pending, since health is assigned at the Pending → Completed transition
- A **Rule Finding** has exactly one **Finding Type** (**Violation** or **Incomplete**), zero or more **Node Findings** (in practice, violations always have at least one), one or more **Classifications** (in practice; a tolerant read drops invalid entries and can serve fewer, even zero), and zero or more **WCAG Criteria**
- A **Score Snapshot** belongs to exactly one **Owner**: an **App** (linked to a **Scan Run**), an **Org Unit** (recomputed via **Org Unit Rollup**), or a **Brand** (recomputed via **Brand Rollup**)
- Deleting an **App** cascades to its **Scan Runs** and **Score Snapshots**; deleting an **Org Unit** that has dependents is refused (**Dependents Guard**)

## Example dialogue

> **Dev:** "Walk me through the ingestion flow — what happens when we upload scan data?"
>
> **Domain expert:** "A **Scan Run** is created in **Pending** status. While it's **Pending**, you add **Page Results** — each one crosses the **Axe Boundary** and stores **Rule Findings** with their **Finding Type** (either **Violation** or **Incomplete**). Then you transition the **Scan Run Status** to **Completed**."
>
> **Dev:** "What triggers scoring?"
>
> **Domain expert:** "The transition to **Completed**. Each **Page Result** gets a **Page Health** based on the worst **Impact** among its **Violations**. Then the **Score** is computed from those **Page Health** categories and saved as a **Score Snapshot**."
>
> **Dev:** "So **Incompletes** don't affect the **Score** at all?"
>
> **Domain expert:** "Correct. **Incompletes** are stored for manual review but excluded from **Page Health** and **Score** computation. Only **Violations** count — and all of them, regardless of **Classification**. A best-practice **Violation** affects the **Score** just like a WCAG one."
>
> **Dev:** "And the **Rollup** happens automatically after that?"
>
> **Domain expert:** "Yes. Once the app's **Score Snapshot** is saved, two rollups fire. The **Org Unit Rollup** cascades up the hierarchy — each ancestor **Org Unit** recomputes its **Score Snapshot** as the mean of its children's latest snapshots. The **Brand Rollup** is flat: it aggregates the latest snapshots across all **Apps** for that **Brand**, regardless of where they sit in the **Org Unit** tree, so moving an **App** between **Org Units** changes the **Org Unit Rollup** but not the **Brand Rollup**."
>
> **Dev:** "What about **Import** — does that follow the same flow?"
>
> **Domain expert:** "Exactly the same. **Import** just automates it — it creates the **App** from the JSON `name` if needed, then uploads each date subdirectory as a separate **Scan Run** through the same Pending → Completed lifecycle."

## Flagged ambiguities

- **"Issue"** was used informally to mean both a **Rule Finding** (a rule that failed) and a **Node Finding** (a specific DOM element). Avoid "issue" entirely: no field or column carries the word today, the snapshot columns that did having been renamed to **Violation** in #18, where it survives as a literal naming what they were called before, as it does in the earlier migration that first created those columns. Use **Violation** when counting failures that affect scoring, **Rule Finding** for the general concept, and **Node Finding** for a specific element instance.
- **"Score"** can refer to the computed value, the value with its counts, or the full persisted record. Use **Score** for the 0–1 value, **Score Aggregates** for the **Score** plus its counts as one unpersisted value, and **Score Snapshot** for the persisted record.
- **"Page"** carries three senses: a URL being tested, the **Page Result** record, and a page of list results in **Cursor Pagination**, carried by the `Page` and `TotaledPage` envelopes. Use **Page Result** for the stored data and "page of results" when talking about pagination. "Page" is acceptable in compound metrics like "pages with violations" where the meaning is clear.
- **"Severity"** and **"Impact"** were used interchangeably. The canonical term is **Impact**, matching axe's own terminology.
- **"Rollup"** covers two distinct patterns: hierarchical cascading (**Org Unit Rollup**) and flat aggregation (**Brand Rollup**). When unqualified, "rollup" means the general concept. Use **Org Unit Rollup** or **Brand Rollup** when the distinction matters.
- **"Status"** is overloaded — **Scan Run Status** (Pending/Completed) vs. the health check endpoint's `"healthy"` status. Context usually disambiguates, but prefer **Scan Run Status** when referring to the lifecycle.
- **"Honesty"** names two unrelated suite-wide invariants: **Declaration Honesty** (an operation declares the 4xx modes it can produce) and import honesty (a private module is reached only from its own package). Neither owns the bare word; say **Declaration Honesty** or "import honesty" in full.
- **"Crossing"** carries two senses: the **Axe Boundary** an **Axe Payload** passes through, and an import that breaks a package-private line. Neither owns the bare word; say **Axe Boundary** for the first, and "a private-module import" or "a sibling import" for the second, which `test_import_honesty.py` and `test_sibling_imports.py` are the checks on.
- **"Ingest"** names the CLI operation **Ingest** (one **Scan Directory** becomes one **Scan Run**) and, lowercase, the server-side act of accepting one **Page Result** through the **Axe Boundary**. Capitalized, it is the CLI operation; for the server side say **Axe Boundary** or "Page Result creation". In a production-code name the CLI operation wins, since `ingest` is its command and its function, and the server side is named for what it does instead: `create_page_result` and `parse_axe_payload`. Test helpers are outside the rule, where `ingest_and_score` and its sibling name the fixture step rather than the CLI operation.
- **"App"** is the domain entity; lowercase `app` is also the ASGI application object the server runs, a name bound outside the repo. In prose say "the ASGI app" or "the application" for the server object, and **App** for the entity. In a name the entity wins, since `app_id` and `AppRead` are the entity throughout; the ASGI object is bound as `app` only in `main.py`, where nothing competes for the word.

## Cross-repo

The UI consumes these terms via the generated client. See `../a11y-health-ui/DOMAIN.md` for any UI-only conventions.
