# Dev Log

## Version 0.7.3 - 2026-04-14

### Context

This update records the backend changes for Ask Patra identity, ICICLE context, and pod-config-managed admin authorization.

### Backend Changes

- Updated the Ask Patra system prompt so the assistant identifies as `Patra`, an ICICLE-aligned PATRA assistant, rather than a generic chatbot or "Ask Patra".
- Added ICICLE context to the default system prompt: ICICLE is the NSF AI Institute for Intelligent Cyberinfrastructure with Computational Learning in the Environment and focuses on trustworthy, democratized AI for cyberinfrastructure-backed science and engineering workflows.
- Kept Ask Patra LLM observability in the backend request path:
  - `ask_patra.answer_question.llm_config`
  - `ask_patra.answer_question.llm_decision`
  - `ask_patra.answer_question.llm_attempt`
  - `ask_patra.answer_question.llm_success`
  - `ask_patra.answer_question.llm_failed`
  - `openai_compat.chat_text.request`
- Clarified runtime behavior: Ask Patra does not call the LLM for low-information greeting messages, but does attempt the LLM for eligible record-search and general-help turns when LLM config and auth are available.
- Moved admin authorization to pod configuration:
  - `PATRA_ADMIN_USERS`
  - `ADMIN_USERNAMES`
- Removed the hardcoded default admin user list from the backend.
- Made the backend authoritative for admin role decisions. Client-supplied `X-Patra-Role: admin` is ignored unless the request username is present in the configured admin list.

### Operational Notes

- To grant admin access in a pod, set `PATRA_ADMIN_USERS` to a comma-separated list of exact Tapis usernames, for example `williamq96,neelk,nkarthikeyan`.
- The frontend may use the same env var for UI visibility, but the backend remains the source of truth for write/admin authorization.

### Validation

- `python -m compileall rest_server` passed.

## Version 0.7.2 - 2026-04-13

### Context

This update records the latest dev backend work for the PATRA planning pipeline, Ask Patra tool orchestration, and LiteLLM/JWT diagnostics.

The main deployment target is now:

- Backend image: `plalelab/patra-backend:WQ-4-12-7`
- Frontend companion image: `plalelab/patra-frontend:WQ-4-13-2`

### Backend Changes

- Confirmed LiteLLM calls can use the request-scoped Tapis user token through `X-Tapis-Token` without treating placeholder service-token values as valid credentials.
- Kept `/api/llm-test/chat` as the vanilla validation path for LLM connectivity, separate from Ask Patra tool orchestration.
- Added route-level diagnostics for Intent Schema and Ask Patra LLM calls so logs show whether request tokens, service tokens, or API keys are selected.
- Fixed the backend Docker image packaging for shared matcher dependencies by including the `src/` matcher package in the runtime image.
- This resolves the deployed error:
  - `ModuleNotFoundError: No module named 'src'`
- Preserved metadata discovery degraded behavior for cases where matcher fallback can still produce a response, while allowing dataset assembly and training-readiness paths to import the shared matcher correctly.
- Updated Ask Patra record handling so requested record counts are honored more tightly and model-card / datasheet requests do not silently over-return unrelated records.
- Normalized Ask Patra assistant Markdown to avoid inline asterisk bullets leaking into the rendered UI.

### Current Behavior Notes

- `Baseline Training Stub` is still intentionally a stub. It does not fit a real model, produce a train/validation/test split, or generate a reusable model artifact.
- When the readiness gate is blocked, the stub should return a blocked readiness/eval report instead of fabricating metrics.
- A blocked report is expected when metadata discovery and dataset assembly find no safe selected dataset and no preview rows.
- The next real training artifact milestone should be a separate executor after the dataset composition manifest and preview path can provide sufficiently covered training candidates.

### Validation

- `python -m compileall rest_server src` passed.
- Container import validation passed:
  - `from src.hybrid_schema_matcher import HybridSchemaMatcher`
  - `from rest_server.patra_agent_service import _modules`
- Docker image `plalelab/patra-backend:WQ-4-12-7` was built and pushed.

## Version 0.7.1 - 2026-04-12

### Context

This update records the current suspended state for the LiteLLM/JWT investigation and the backend changes shipped in Docker tag `WQ-4-12-2`.

The active blocker is not route registration. The backend confirms the relevant routes are enabled and registered. The blocker is LiteLLM authorization: calls to `https://litellm.pods.tacc.tapis.io/v1/chat/completions` still return `403 Forbidden` unless a valid service token or user Tapis JWT with LiteLLM access is supplied.

Work is paused until the Tapis Pods maintainer can provide or validate a service token for the dev backend pod.

### Backend Changes

- Added a minimal vanilla LLM test endpoint:
  - `POST /api/llm-test/chat`
- Included the LLM test route when Ask Patra routes are enabled.
- The endpoint intentionally bypasses:
  - Ask Patra intent classification
  - tool registry
  - citation lookup
  - starter prompts
  - inline execution
  - workflow handoff logic
- The endpoint sends the user message directly through the shared OpenAI-compatible client so it can isolate LiteLLM/JWT behavior.
- On failure, the endpoint returns a structured error response instead of falling back to deterministic text.
- Added non-sensitive diagnostics for:
  - route-level token/header presence
  - selected auth source: service token, request token, API key, or none
  - OpenAI-compatible request header presence
  - HTTP status, redirect location, and short response body on upstream failure
- Added placeholder-token detection so values like `<valid Tapis JWT/service token with LiteLLM access>` are not treated as real credentials.
- Added service-token env aliases:
  - `ASK_PATRA_TAPIS_TOKEN`
  - `INTENT_SCHEMA_TAPIS_TOKEN`
  - `LITELLM_TAPIS_TOKEN`
  - `PATRA_LITELLM_TAPIS_TOKEN`
- Updated MCP inline execution to read `MCP_BASE_URL` from environment instead of using a local hardcoded endpoint.

### Current Suspended State

- `Ask Patra` and `Intent Schema` are still expected to fall back when LiteLLM returns `403 Forbidden`.
- `LLM Test` should now be used as the primary validation surface because it does not involve tool orchestration.
- If `/llm-test` logs `selected=service` and sends both `Authorization` and `X-Tapis-Token` but still receives `403`, the installed token lacks LiteLLM access.
- If `/llm-test` logs `selected=none`, the pod still does not have a usable token configured.

### Docker Images

- Backend image pushed: `plalelab/patra-backend:WQ-4-12-2`
- Frontend companion image expected for the same test run: `plalelab/patra-frontend:WQ-4-12-2`

### Validation

- `python -m compileall rest_server` passed.

## Version 0.7.0 - 2026-04-10

### Context

The current backend work now splits into two tracks:

- the intent-driven MVP demo pipeline framework is largely assembled at the API level
- the next active milestone is Ask Patra tool unification, where Ask Patra becomes the routing layer for user-facing PATRA tools

### Current MVP Demo Status

- The backend already exposes the high-level demo pipeline surfaces for:
  - intent schema
  - metadata discovery
  - dataset assembly
  - composition preview
  - training readiness
  - baseline training stub
  - MVP demo report
- The framework is now sufficiently complete for architectural demonstration.
- The remaining instability is believed to be concentrated in LLM invocation / integration behavior rather than missing deterministic pipeline modules.
- That issue is temporarily paused so it can be repaired as a separate stabilization task.

### New Active Milestone

- Ask Patra now becomes the active integration priority.
- First-stage Ask Patra scope is:
  - deterministic-first intent routing
  - user-tool registry
  - hybrid navigation / handoff behavior
  - no admin-only surfaces in the first pass

### Action Points

- Keep the MVP demo branch documented but paused until LLM invocation stability is revisited.
- Proceed with Ask Patra tool orchestration as the next backend-facing integration milestone.

## Version 0.6.3 - 2026-04-07

### Context

This patch fixes backend startup regressions introduced by the SQL/workflow merge so the API process can import cleanly in pod deployments again.

### Problem

- `rest_server.routes.submissions` imported submission workflow models that were missing from `rest_server.workflow_models`.
- Datasheet and model-card update routes imported `DatasheetUpdate` and `ModelCardUpdate`, but those update models were missing from `rest_server.models`.
- As a result, the backend pod failed during app import before Uvicorn could finish startup.

### Implementation

- Restored submission workflow request/response models in `rest_server.workflow_models`:
  - `SubmissionCreate`
  - `SubmissionBulkCreate`
  - `SubmissionReviewUpdate`
  - `SubmissionRecord`
  - bulk result models
- Restored asset update models in `rest_server.models`:
  - `AIModelUpdate`
  - `ModelCardUpdate`
  - `DatasheetUpdate`
- Revalidated the full import path by importing `rest_server.main` directly.

### Validation

- `python -m compileall rest_server` -> passed
- `import rest_server.main` -> passed

### Action Points

- Redeploy backend with the patched image instead of `2026-04-07-v0-6-2`.
- Update the stable frontend env typo (`Key2SUPPORTS_EDIT_RECORDS`) before testing edit flows.

## Version 0.6.2 - 2026-04-07

### Context

This patch records the backend alignment work needed to support the shared frontend experiment surfaces and to keep the API process usable even when the database is slow or unavailable during pod startup.

### Problem

- The frontend now expects first-class support for two experiment domains:
  - `animal-ecology`
  - `digital-ag`
- Experiment pages need dedicated API routes for users, summaries, lists, images, and deployment power data.
- In environments where the database is unavailable at startup, the backend previously failed hard instead of exposing a degraded-but-running API process.

### Implementation

- Added experiment API models for:
  - users
  - summaries
  - experiment lists
  - experiment detail
  - image rows
  - deployment power detail
- Added `/experiments/...` routes for:
  - user listing
  - per-user summaries
  - experiment lists
  - experiment detail
  - image rows
  - power data
- Extended bootstrap schema support for:
  - `camera_trap_events`
  - `camera_trap_power`
  - `digital_ag_events`
  - `digital_ag_power`
  - supporting user / device columns needed by the experiment views
- Registered the experiment router in the main FastAPI app.
- Switched database-pool dependency failure from raw runtime exception to explicit `503 database unavailable`.
- Added startup-time tolerance so the API can enter a degraded mode when the database does not initialize within the configured timeout.

### Validation

- `python -m compileall rest_server` -> passed
- Confirmed route registration and model/schema wiring for the experiment endpoints
- Confirmed degraded-startup path returns controlled API errors instead of crashing the process

### Action Points

- Apply the schema changes to the live database before relying on experiment pages in production.
- Configure database startup timing and readiness expectations explicitly in pod deployments if degraded startup is intended.

## Version 0.6.1 - 2026-04-06

### Context

This patch hardens the backend behavior behind `Ask Patra` so the assistant stays concise for greetings and broad questions, while still supporting grounded record lookup when the user clearly asks for it.

### Problem

- Generic messages such as `hi` could still trigger record search and large citation payloads.
- Default Ask Patra prompt templates did not sufficiently constrain output length or lookup behavior.
- Existing default prompt files persisted on disk, which meant upgraded prompt logic could be ignored by already-initialized environments.
- Record citation sets could include near-duplicate items and create noisy assistant output.

### Philosophy

- Do not treat every user message as a search request.
- Keep answers short unless the user explicitly asks for depth.
- Use retrieval only when the user intent actually indicates a record lookup.
- Preserve prompt-template editability while still allowing safe automatic upgrades from earlier defaults.

### Implementation

- Added greeting / capability-question / lookup-intent classification for Ask Patra prompts.
- Prevented greeting-style messages from triggering record retrieval or LLM lookup expansion.
- Tightened the default Ask Patra system and behavior prompts to enforce:
  - concise answers
  - selective citations
  - no long record dumps for vague prompts
  - Markdown-friendly formatting
- Added prompt-template upgrade logic so older default on-disk prompt files are refreshed automatically, while custom-edited prompt files remain untouched.
- Added citation deduplication so repeated near-identical records do not dominate the answer context.
- Updated fallback answers so greetings and PATRA-capability questions now return short, structured responses instead of broad record lists.

### Validation

- `python -m compileall rest_server` -> passed
- Verified local Ask Patra behavior:
  - `hi` is classified as greeting
  - greeting does not trigger lookup
  - explicit lookup still triggers retrieval
- Verified fallback greeting output is concise and Markdown-structured.

### Action Points

- Deploy the `0.6.1` backend patch alongside the matching Ask Patra frontend update.
- Continue keeping retrieval gating and response-length controls close to the Ask Patra service layer so future provider changes do not alter user-visible behavior unexpectedly.

## Version 0.6.0 - 2026-04-06

### Context

This milestone extends the PATRA backend from a catalog and moderation API into a broader agent-driven workflow backend. The system now includes the `Ask Patra` assistant surface, automated external CSV ingestion into an isolated ingestion pool, stronger OpenAI-compatible provider plumbing, and a cleaner alignment with frontend feature modularization and group-based access expectations.

### Problem

- PATRA’s new frontend capabilities required corresponding backend services rather than ad hoc mock behavior:
  - conversational assistant support
  - scrape-and-validate CSV ingestion
  - isolated artifact review without contaminating the main pool
- LLM-backed flows needed more operational tolerance:
  - local LM Studio during development
  - future LiteLLM / SambaNova integration in Pods
  - fallback behavior when structured outputs are unavailable
- CSV ingestion could not directly enter the public resource pool without a staging boundary and explicit admin review.
- Assistant and ingestion work needed clearer module boundaries in the backend codebase.

### Philosophy

- Keep LLM usage bounded and replaceable:
  - OpenAI-compatible provider interface
  - deterministic fallback where necessary
  - strict schema expectations for machine-readable outputs
- Stage externally discovered data in a dedicated internal pool before any promotion decision.
- Organize backend feature work around product capabilities, not just route files.
- Preserve auditability and moderation boundaries even when the frontend moves toward more direct or conversational workflows.

### Implementation

- Added backend support for `Ask Patra`:
  - dedicated route surface
  - prompt / memory storage paths
  - OpenAI-compatible provider helper suitable for LM Studio now and LiteLLM / SambaNova later
- Added automated ingestion backend flow with:
  - `scraper_jobs`
  - isolated ingestion-artifact persistence
  - code-level CSV discovery and validation
  - LLM semantic validation and datasheet draft generation
  - admin review state transitions without promotion into the main pool
- Expanded Hugging Face tolerance so dataset-page URLs can resolve CSV candidates rather than requiring only direct CSV links.
- Added ingestion fallback logic so LLM validation and draft generation can fall back to deterministic code paths instead of failing the entire job.
- Improved model/provider selection logic for local OpenAI-compatible endpoints so generation models are preferred over embedding-style endpoints.
- Added artifact download endpoints and richer artifact-detail payloads for frontend review workflows.
- Continued backend feature modularization under `rest_server/features` with per-feature documentation.

### Validation

- Backend compile validation completed after the new assistant and ingestion routes landed.
- End-to-end local ingestion validation completed for:
  - direct CSV URLs
  - Hugging Face dataset-page discovery
  - isolated ingestion-pool artifact creation
  - fallback and non-fallback LLM paths
- Local Ask Patra bootstrap and chat endpoints were verified against LM Studio.

### Action Points

- Keep the OpenAI-compatible provider boundary stable so Tapis deployment can switch from LM Studio to LiteLLM / SambaNova by configuration only.
- Continue separating ingestion-pool review from main-pool publication until a dedicated promote-to-main workflow is designed.
- Mirror any backend feature-folder conventions into frontend docs so cross-repo navigation stays predictable.

## Version 0.1.6 - 2026-03-15

### Context

After the live frontend was updated to read from the PostgreSQL-backed backend, model card and datasheet detail pages still failed in practice. The regression surfaced as frontend `not found` pages for detail navigation, and a deeper live validation pass also exposed a backend-only datasheet detail failure when geo-location polygons were stored as null-like values.

### Problem

- The active frontend and backend had drifted on list/detail payload contracts:
  - model-card list responses return `mc_id`, while the older UI expected `id`
  - datasheet list responses return `identifier`, while the older UI expected `id`
- Datasheet detail responses could fail with `500` when `datasheet_geo_locations.polygon` was stored as a JSON stringified null value.
- End-to-end moderation workflows needed to be revalidated after the detail-page repair:
  - asset submission
  - support ticket submission
  - admin approval / resolution

### Engineering Approach

- Leave the frontend-facing backend contract unchanged and harden the backend around the live datasheet edge case instead of introducing a second round of API churn.
- Fix geo-location writes and reads together so newly created rows do not persist invalid null polygons and existing rows remain readable.
- Revalidate the full submission / ticket / admin-review workflow through the actual HTTP/UI surfaces, not just isolated route tests.

### Implementation

- Updated `rest_server/routes/assets.py` so datasheet geo-location inserts now write `NULL` for `polygon` when the payload omits polygon data, instead of serializing Python `None` to the string `"null"`.
- Updated `rest_server/routes/datasheets.py` to normalize `polygon` values defensively on read:
  - `None`
  - empty string
  - string `"null"`
  - JSON strings that decode to non-object values
- Confirmed live moderation flow behavior against the running local stack:
  - `POST /submissions`
  - `PUT /submissions/{id}`
  - `POST /tickets`
  - `PUT /tickets/{id}`
  - final asset publication through approval-time ingest helpers

### Validation

- Local live-stack browser validation completed successfully:
  - asset-link submission queued
  - admin approval created a real model card record
  - support ticket submission succeeded
  - admin resolution persisted and became visible to the submitting user
- Direct API verification confirmed:
  - approved submission stored `created_asset_id`
  - resolved ticket stored `reviewed_by` and `admin_response`
  - `GET /datasheet/{identifier}` returned `200` after the geo-location hardening fix

## Version 0.1.5 - 2026-03-13

### Context

The frontend was successfully connected to live PostgreSQL-backed reads, but the collaboration workflows were still incomplete. `/tickets` and `/submissions` remained unimplemented, so the personalized dashboard, ticket pages, and admin review queue could not operate against the live backend.

### Problem

- End users could submit assets directly to `/v1/assets/*`, but there was no real pending review queue.
- The frontend expected `/tickets` and `/submissions`, but the backend did not expose those routes.
- Admin-only review actions had no server-side surface at all.
- The Tapis account `williamq96` needed to be treated as an admin session in the live workflow.

### Engineering Approach

- Keep the existing asset ingest endpoints as the final publication path.
- Introduce a separate queue layer for moderation: pending submissions live in `submission_queue` until explicitly approved.
- Keep ticketing simple and operational: one table, one list/create/update surface, and admin-only resolution updates.
- Reuse the existing asset-ingest transaction helpers on approval so accepted submissions land in the production catalog through the same code path as direct ingest.

### Implementation

- Added `support_tickets` and `submission_queue` to `db/bootstrap_schema.sql`.
- Added backend actor/admin helpers in `rest_server/deps.py`, with `williamq96` included in the default admin allowlist.
- Added `rest_server/workflow_models.py` for ticket and submission API contracts.
- Added `rest_server/routes/tickets.py` with:
  - `GET /tickets`
  - `POST /tickets`
  - `PUT /tickets/{id}` for admin review/response
- Added `rest_server/routes/submissions.py` with:
  - `GET /submissions`
  - `POST /submissions`
  - `POST /submissions/bulk`
  - `PUT /submissions/{id}` for admin review
- Submission queue rows now store both:
  - display-oriented submission data for the frontend review UI
  - `asset_payload` for final approval-time publication
- Approval of a queued submission now reuses the existing asset-ingest helpers to create the real `model_cards` / `datasheets` records.

### Validation

- `pytest tests/test_workflow_api.py tests/test_asset_ingest_api.py tests/test_database_config.py tests/test_privacy.py -q` -> `36 passed`

## Version 0.1.4 - 2026-03-13

### Context

After the frontend was switched to the PostgreSQL-backed asset ingestion API, the live backend still failed at runtime in Pods. Public read endpoints crashed with `UndefinedTableError` because the connected PostgreSQL database had not been initialized with the expected Patra schema, and frontend-driven asset submissions could not authenticate because the asset ingest API only accepted organization API keys.

### Problem

- `GET /modelcards` failed because relation `model_cards` did not exist.
- `GET /datasheets` failed because relation `datasheets` did not exist.
- The active backend image assumed database migrations had already been run externally.
- The frontend submits assets using a Tapis user session, but `/v1/assets/*` only accepted `X-Asset-Org` plus `X-Asset-Api-Key`.

### Engineering Approach

- Treat schema availability as an application startup responsibility for the active Pods deployment, not as an undocumented manual prerequisite.
- Avoid using the destructive migration file at runtime; bootstrap only the missing schema objects with idempotent `CREATE ... IF NOT EXISTS`.
- Preserve existing organization API-key ingestion for partner integrations while also allowing the first-party frontend to write assets via the same Tapis-token model already used for private asset reads.

### Implementation

- Added `db/bootstrap_schema.sql` with idempotent creation of:
  - `approval_status`
  - `model_cards`, `models`
  - `datasheets`, `publishers`, and all DataCite child tables
  - `users`, `edge_devices`, `experiments`, `raw_images`, `experiment_images`
  - supporting indexes
- Updated `rest_server/database.py` so `init_pool()` now calls `ensure_schema()` immediately after the asyncpg pool is created.
- Updated `rest_server/Dockerfile` to copy the `db/` directory into the container image so the bootstrap SQL is available at runtime.
- Updated `rest_server/deps.py` so `/v1/assets/*` accepts a non-empty `X-Tapis-Token` as a first-party ingest principal (`organization="tapis"`), while keeping the existing API-key path intact for external organizations.

### Validation

- `pytest tests/test_database_config.py -q` -> `3 passed`
- `pytest tests/test_asset_ingest_api.py -q` -> `7 passed`
- `pytest tests/test_privacy.py -q` -> `23 passed`

## Version 0.1.3 - 2026-03-12

### Context

After the initial Pods TLS workaround shipped, a new runtime failure appeared during PostgreSQL pool initialization. The error changed from handshake reset behavior to `ConnectionDoesNotExistError: connection was closed in the middle of operation`, which warranted a direct reproduction against the live database endpoint.

### Problem

- The `0.1.2` workaround forced `direct_tls=True` for `.pods.icicleai.tapis.io:443`.
- Direct reproduction showed that this assumption was incorrect for the Patra database endpoint.
- The real working combination for `patradb.pods.icicleai.tapis.io:443` is regular TLS with `sslmode=require`, not `direct_tls=True`.

### Engineering Approach

- Reproduce the exact `asyncpg` connection mode against the live endpoint instead of reasoning from the stack trace alone.
- Treat the runtime behavior as the source of truth and roll back the incorrect transport assumption.
- Keep the safe parts of the earlier fix: rewriting Pods-host DSNs from `5432` to `443`, and extracting `sslmode` into an explicit SSL context.

### Implementation

- Removed the forced `direct_tls=True` behavior from `rest_server/database.py`.
- Kept the Pods-specific port rewrite from `5432` to `443`.
- Kept explicit `sslmode=require` handling with a non-verifying SSL context for the existing deployment model.
- Updated `tests/test_database_config.py` so Pods-host connections are expected to use `direct_tls=False`.

### Diagnosis Summary

The failing backend image was using the wrong transport setting. For the current Patra database endpoint, `asyncpg` succeeds with:

- host `patradb.pods.icicleai.tapis.io`
- port `443`
- `sslmode=require`
- `direct_tls=False`

The previous image forced `direct_tls=True`, which caused the database connection to be closed mid-operation during startup.

### Validation

- `pytest tests/test_database_config.py -q` -> `3 passed`
- `pytest tests/test_privacy.py -q` -> `23 passed`
- `pytest tests/test_asset_ingest_api.py -q` -> `6 passed`

## Version 0.1.2 - 2026-03-12

### Context

After publishing the PostgreSQL-backed backend image, the runtime still failed in Pods during application startup. The process did not fail in request handling code; it failed while initializing the async PostgreSQL pool.

### Problem

- The backend exited during FastAPI startup while connecting to PostgreSQL on the Tapis Pods host.
- The failure surfaced as `ConnectionResetError` inside `uvloop.start_tls`, after repeated retries.
- This indicated the process was reaching the remote endpoint, but the TLS negotiation mode used by `asyncpg` did not match what the Pods-facing PostgreSQL endpoint expected.

### Engineering Approach

- Treat the failure as a transport mismatch rather than a schema or credential issue.
- Preserve the existing PostgreSQL DSN flow, but make the connection builder aware of the Tapis Pods 443 endpoint behavior.
- Add regression tests around connection option construction so the runtime does not silently fall back to the wrong handshake path later.

### Implementation

- Replaced the old DSN helper with `_build_connection_options()` in `rest_server/database.py`.
- For hosts ending with `.pods.icicleai.tapis.io` on port `443`, the backend now sets `direct_tls=True` when creating the asyncpg pool.
- Existing `sslmode=require` handling remains in place, but the connection is now established with direct TLS instead of PostgreSQL SSLRequest upgrade semantics for that Pods endpoint.
- Added `tests/test_database_config.py` to verify:
  - Tapis Pods DSNs are rewritten to port `443`
  - Tapis Pods connections enable `direct_tls=True`
  - non-Pods PostgreSQL hosts continue to use regular TLS behavior

### Diagnosis Summary

The startup failure was caused by using the wrong TLS negotiation mode for the Pods-facing PostgreSQL endpoint. The endpoint was reachable, but it reset the connection during `start_tls`, which is consistent with an endpoint expecting direct TLS instead of a later protocol upgrade.

### Validation

- `pytest tests/test_database_config.py -q` -> `3 passed`
- `pytest tests/test_privacy.py -q` -> `23 passed`
- `pytest tests/test_asset_ingest_api.py -q` -> `6 passed`

## Version 0.1.1 - 2026-03-12

### Context

Version `0.1.1` captures the follow-up operational hardening after the PostgreSQL migration path was established. The main goals were to make the Neo4j suspension explicit at repository entry points, improve Docker runtime diagnostics for the active backend, and document a supported container workflow instead of leaving the suspended legacy compose file as the only visible example.

### Problem

- Neo4j code had been retained in-repo, but several entry points still looked runnable and could mislead future maintenance or deployment work.
- The active FastAPI container did not expose explicit liveness/readiness endpoints, which made it harder to distinguish application failure from orchestration failure.
- The repository did not contain a supported PostgreSQL-based compose file for the active backend, while the only root compose file was tied to the suspended Neo4j stack.

### Engineering Approach

- Preserve legacy code for reference, but label it as suspended exactly where operators and developers encounter it.
- Add health surfaces that let container platforms determine whether the process is alive and whether PostgreSQL is reachable.
- Make the container runtime more platform-friendly by honoring `PORT` and by providing a default health check inside the backend image.
- Add a dedicated PostgreSQL compose file for the active backend instead of mutating the suspended legacy compose file into a dual-purpose artifact.

### Implementation

- Marked Neo4j-oriented files and services as suspended in:
  - `README.md`
  - `docker-compose.yml`
  - `Makefile`
  - `legacy_server/server.py`
  - `mcp_server/main.py`
  - `ingester/neo4j_ingester.py`
  - `reconstructor/mc_reconstructor.py`
- Added `/healthz` and `/readyz` to the active FastAPI app.
- Updated the backend Docker image so it:
  - performs a health check against `/healthz`
  - respects `${PORT}` for managed container platforms
- Added a supported PostgreSQL-based compose file at `docker-compose.backend.yml`.

### Run Commands

Local Python run:

```powershell
$env:DATABASE_URL="postgresql://patra:patra-dev-password@localhost:5432/patra"
$env:PATRA_ASSET_INGEST_KEYS_JSON='{"org-a":"change-me"}'
python -m uvicorn rest_server.main:app --host 0.0.0.0 --port 8000 --proxy-headers
```

Docker Compose run:

```powershell
docker compose -f docker-compose.backend.yml up --build
```

Docker Compose stop:

```powershell
docker compose -f docker-compose.backend.yml down
```

### Docker Compose File

The supported active-backend compose file is committed as `docker-compose.backend.yml`:

```yaml
services:
  postgres:
    image: postgres:16
    container_name: patra-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-patra}
      POSTGRES_USER: ${POSTGRES_USER:-patra}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-patra-dev-password}
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    volumes:
      - patra_postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-patra} -d ${POSTGRES_DB:-patra}"]
      interval: 10s
      timeout: 5s
      retries: 5

  patra-backend:
    build:
      context: .
      dockerfile: rest_server/Dockerfile
    container_name: patra-backend
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      PORT: 8000
      DATABASE_URL: postgresql://${POSTGRES_USER:-patra}:${POSTGRES_PASSWORD:-patra-dev-password}@postgres:5432/${POSTGRES_DB:-patra}
      PATRA_ASSET_INGEST_KEYS_JSON: '{"org-a":"change-me"}'
    ports:
      - "${BACKEND_PORT:-8000}:8000"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]
      interval: 30s
      timeout: 5s
      start_period: 15s
      retries: 3

volumes:
  patra_postgres_data:
```

### Diagnosis Summary

The backend codebase did not contain any timer-driven or explicit self-termination logic. The stronger operational suspicion was orchestration behavior rather than application exit, especially for environments that enforce idle or time-based shutdown policies. Health endpoints and image-level health checks were added to make future diagnosis observable instead of inferential.

### Validation

- `pytest tests/test_privacy.py -q` -> `23 passed`
- `pytest tests/test_asset_ingest_api.py -q` -> `6 passed`
- `pytest tests/test_mcp_server.py -q` -> `31 passed`

## Version 0.1.0 - 2026-03-12

### Context

Patra's active backend path is now `rest_server/` with FastAPI and PostgreSQL. The Neo4j-backed Flask, MCP, ingester, and reconstructor code remains in-repo for archive/reference compatibility, but it is suspended and is no longer the supported runtime or integration surface.

### Problem

The backend had drifted from the frontend and from the current deployment model in two important ways:

- The active API surface did not fully cover frontend usage patterns such as protected asset retrieval behaviors and direct asset ingestion for external organizations.
- Repository-level docs and operational entry points still implied Neo4j was an active backend path, which no longer matched the system architecture.

### Engineering Approach

The implementation followed four principles:

- Treat PostgreSQL as the system of record and avoid reintroducing graph-backed runtime dependencies.
- Add direct ingestion APIs for partner organizations so assets can be injected without going through the frontend.
- Make authorization explicit and narrow for write operations, with configuration-driven credentials and bounded request shapes.
- Normalize client-visible behavior for unauthorized or nonexistent assets so the backend does not leak existence information.

### Design Decisions

- Added protected asset ingestion endpoints under `/v1/assets` instead of extending public read APIs. This keeps external write access isolated and easier to secure.
- Used per-organization API keys from `PATRA_ASSET_INGEST_KEYS_JSON` with support for either plaintext secrets or `sha256:` digests. Secret comparison uses constant-time checks.
- Rejected unsafe dynamic keys in user-controlled maps such as `model_metrics`, `bias_analysis`, and `xai_analysis` to reduce the risk of injection through dynamic payload content.
- Standardized inaccessible asset reads to the same `404` detail, `assets not avaible or not visible.`, so callers cannot distinguish between missing and unauthorized assets.
- Marked Neo4j-related compose, Make, Flask, MCP, ingester, and reconstructor paths as suspended instead of deleting them, preserving reference value without presenting them as supported runtime paths.

### Implementation

Implemented PostgreSQL-backed asset ingestion APIs for external organizations:

- `POST /v1/assets/model-cards`
- `POST /v1/assets/model-cards/bulk`
- `POST /v1/assets/datasheets`
- `POST /v1/assets/datasheets/bulk`

Supporting changes:

- Added request models and validators for model card and datasheet ingestion payloads.
- Added authentication dependencies for organization-scoped API key access.
- Added duplicate detection and per-item bulk ingest reporting.
- Added model download and deployment read endpoints required by current client behavior.
- Updated privacy-facing read routes so nonexistent and non-visible assets return the same `404` detail.

### Security Considerations

- Asset ingest endpoints fail closed with `503` when credential configuration is absent or invalid.
- Write access requires both organization identity and a valid secret supplied via `X-Asset-Api-Key` or `Authorization: Bearer`.
- Secret matching uses `hmac.compare_digest`.
- Unsafe dynamic keys are rejected at validation time with `422`.
- Bulk ingestion reports item-level failures without exposing internal SQL details to callers.

### Validation

Verified with targeted automated tests:

- `pytest tests/test_asset_ingest_api.py -q` -> `6 passed`
- `pytest tests/test_privacy.py -q` -> `21 passed`
- `pytest tests/test_mcp_server.py -q` -> `31 passed`

### Operational Notes

- New backend work should target `rest_server/` only.
- Neo4j-oriented `docker-compose.yml`, `Makefile`, `legacy_server/`, and `mcp_server/` are suspended and retained for archive/reference only.
- External organizations can now inject assets directly through the protected `/v1/assets` API without depending on frontend workflows.

### Next Steps

- Publish the new asset ingestion endpoints and auth contract in user-facing API documentation.
- Add finer-grained ingest scopes if different organizations should have different write permissions.
- Continue aligning any remaining frontend-only workflows against the PostgreSQL API surface instead of reviving legacy graph paths.
