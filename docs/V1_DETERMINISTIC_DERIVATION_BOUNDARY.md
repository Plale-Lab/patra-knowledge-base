# PATRA — V1 Deterministic Derivation Boundary

| Field | Value |
|-------|--------|
| **Version** | 1.0 |
| **Status** | Normative for missing-column feasibility and bounded synthesis in PATRA Agent Tools |
| **Normative implementation** | `src/missing_column_derivation.py` |
| **Downstream enforcement** | `rest_server/patra_synthesis_service.py`, `rest_server/routes/agent_tools.py` |

## 1. Platform context

**PATRA** is a **model-card and dataset reproducibility** platform: it applies across **research domains** (e.g. ML benchmarks, scientific datasets, operational telemetry—not any single vertical). Users declare **schemas** (fields, attributes, types) and link them to **assets** with **auditable** provenance.

The **V1 Deterministic Derivation Boundary** applies to **substitution-style workflows**: when a **query schema** (from a paper, spec, or hand-authored JSON) is compared to a **candidate dataset schema**, PATRA classifies each **target attribute** as either already supported by the candidate, **deterministically derivable** from observable source columns, or **explicitly out of scope** for automated derivation.

## 2. Purpose of the boundary

The boundary defines **which gaps may be closed with strict, code-defined transforms**—same inputs, same outputs, named source columns, reviewable checks. It exists to:

- Prevent **implicit dataset substitution** and **hallucinated values**.
- Keep coverage **explicit**: “derivable” is always tied to a named rule and evidence.
- Stay **inclusive of any topic**: query schemas may use **any property names**; only **rules that exist in the V1 catalog** can mark an attribute as derivable. All other names remain **`not safely derivable`** until a normative rule is added (see §8).

## 3. Scope

**In scope (V1)**

- Per-attribute feasibility: `directly available` | `derivable with provenance` | `not safely derivable`.
- Optional **materialization** of attributes marked `derivable with provenance`, via a deterministic executor, validation, and (where applicable) PATRA **admin review** before shared-pool admission.

**Out of scope (V1)**

- Probabilistic imputation, learned cross-schema mappings, or LLM-generated cell values presented as facts.
- Derivations that are not implemented as explicit, test-covered rules in `src/missing_column_derivation.py`.
- Certain ingestion paths may reject specific file formats (e.g. PDF) independently of this boundary.

## 4. Definitions

| Term | Meaning |
|------|---------|
| **Target attribute** | A key in `query_schema.properties`—any name the user or extractor placed in the query schema (climate series, HPC job fields, biomarkers, survey items, etc.). |
| **Candidate normalized schema** | Schema aligned to a **public or internal candidate dataset**; properties may reuse PATRA conventions or dataset-native names. |
| **Raw schema** | Column names as stored in the **source artifact** (CSV headers, table fields); used for alias resolution and provenance. |
| **Deterministic rule** | A fixed predicate + transform family in code; auditable checks are recorded with the decision. |
| **V1 catalog** | The **closed set** of rules in §6 at this revision. **Default deny** for all targets not matched. |
| **Baseline paper extraction** | `src/paper_schema_parser.py` maps selected tabular patterns to a **starter set** of canonical keys for demos; **pasted or uploaded JSON schemas** can describe **arbitrary** attributes without using that mapping. |

## 5. Safety model

1. **Default deny:** No matching rule ⇒ **`not safely derivable`**.
2. **No silent success:** `derivable with provenance` requires identifiable **source columns** and stated **checks** (see implementation).
3. **LLM role (when enabled):** **Planning only**; execution and validation remain deterministic. LLMs do not author authoritative values for release.
4. **Governance:** Synthesized artifacts are subject to PATRA **review workflows** before broad **shared-pool** admission where the product enforces that gate.

## 6. V1 rule catalog (normative)

Rules are evaluated **per target attribute** in `query_schema.properties`, in implementation order. This catalog is **domain-illustrative**: the identifiers below originated in geospatial + **time-series telemetry** exemplars (including crop and environmental use cases). The **same mechanism** applies to **any future rule** added for other domains (e.g. workload traces, genomics metadata)—new keys, same classification contract.

### 6.1 Direct coverage

| Condition | Classification |
|-----------|----------------|
| Target key exists on the **candidate normalized schema** | `directly available` |

### 6.2 Built-in derivations (raw-schema evidence required)

Unless noted, matching uses **case-insensitive substring** heuristics on **raw** column names (see code). Monthly-like targets additionally require **date / time / year** signals in raw columns.

| Target key | Intended semantics (informative) | Evidence / transform family |
|------------|----------------------------------|-----------------------------|
| `LAT` | Latitude | Alias normalization from raw latitude columns |
| `LON` | Longitude | Alias normalization from raw longitude columns |
| `Year` | Calendar year | Direct year column or **deterministic** year-from-date extraction |
| `yield` | Scalar outcome / mass yield | Yield-like columns or long-form **value + element** filter |
| `Tmax_monthly` | Monthly max temperature series | Dated Tmax observations → monthly aggregation |
| `Tmin_monthly` | Monthly min temperature series | Dated Tmin observations → monthly aggregation |
| `PRE_monthly` | Monthly precipitation series | Dated precipitation observations → monthly aggregation |
| `NDVI_monthly` | Monthly vegetation index series | Dated NDVI observations → monthly aggregation |
| `SM_monthly` | Monthly soil moisture series | Dated soil-moisture observations → monthly aggregation |

### 6.3 Explicit rejection

If **no** rule in §6.1–6.2 applies:

**`not safely derivable`** — *"No strict deterministic derivation rule is available for this target attribute under the current V1 boundary."*

Examples today include attributes such as **`DEM`** or **`SSD_monthly`** until a **normative** rule and executor path are added.

## 7. Schema pool vs. derivation boundary

The **default bundled public schema pool** used in Agent Tools development (`build_default_public_schema_pool` / legacy `build_wheat_vertical_schema_pool`) is a **multi-dataset exemplar catalog** for demos and regression—not a statement that PATRA is limited to any one topic. **Substitution logic** (search + feasibility + synthesis) applies to **whatever pool and query schema** the deployment configures.

## 8. Extending PATRA (new domains and attributes)

To support **new fields or disciplines** in an inclusive way:

1. Add **deterministic** matchers and decisions to `src/missing_column_derivation.py` (and tests in `tests/test_missing_column_derivation.py`).
2. Extend **materialization** in `rest_server/patra_synthesis_service.py` only for rules that are actually executable with provenance.
3. Optionally extend **tabular paper extraction** mappings in `src/paper_schema_parser.py`, or rely on **JSON/query schemas** supplied directly for domains without table templates.
4. Bump **spec version** (patch vs minor) per your change-management policy and update this document’s rule table.

## 9. Change control

- **Patch (V1.x):** Clarifications, stricter checks, bug fixes **without** new target families.
- **Minor (V1 → V2):** New **normative** rule families or breaking classification semantics—update version, tests, synthesis gates, and this document.

## 10. References (informative)

- Workflow philosophy: `PATRA/patra-backend-src/dev_log.md`
- Agent Tools UI: `patra-frontend-src/app/src/views/AgentToolsView.vue`
