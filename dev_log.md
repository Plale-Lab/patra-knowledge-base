# Dev Log

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
