## [Unreleased]

### Added
- Mocked/deterministic unit and route tests for four previously zero-coverage modules:
  `rest_server/features/shared/openai_compat.py`, `rest_server/routes/agent_tools.py`,
  `rest_server/features/ask_patra/` (service + routes), and `rest_server/routes/experiments.py`.
  No live database, LLM, or network calls required — `httpx.Client` is mocked at the boundary for
  `openai_compat.py`, and `agent_tools`/`ask_patra`/`experiments` routes are tested against
  hand-rolled mock asyncpg pools. `ask_patra` and `experiments` are gated behind
  `ENABLE_ASK_PATRA`/`ENABLE_DOMAIN_EXPERIMENTS`, which are checked at `rest_server.main` import
  time, so their route tests reload that module with the flag set rather than relying on the
  shared `client` fixture. Added `pytest-cov` + `.coveragerc` (`source = rest_server, shared`);
  CI now reports coverage on every run.

### Removed
- The bulk asset-ingest endpoints, `POST /v1/assets/model-cards/bulk` and
  `POST /v1/assets/datasheets/bulk`. Nothing in `patra-frontend` called them (only
  external API-key partner consumers could have), and the underlying create logic
  (`_create_model_card_in_tx`/`_create_datasheet_in_tx`) is unaffected — the single-record
  `POST /v1/assets/model-cards` and `POST /v1/assets/datasheets` endpoints are unchanged.
  The `PATCH` update endpoints are untouched by this change.

### Known issues found by the new tests (not fixed — flagged for the maintainer)
- `rest_server/features/ask_patra/service.py`: `_is_greeting()` lists `"hello!"` and `"hey!"` in
  its target set of exact greeting matches, but never actually matches them. The function only
  treats a message as a "bare" greeting when tokenization produces zero tokens, and the tokenizer
  drops tokens of length <= 2 — so `"hi!"` (tokenizes to nothing) is recognized, but `"hello!"`
  and `"hey!"` (5- and 3-character tokens survive tokenization) are not, despite being explicitly
  listed as intended matches.

## [v1.0.0] - 2026-08-12

First stable release. The FastAPI + PostgreSQL REST service under `rest_server/` is now the
supported backend, and its HTTP API is covered by semantic versioning: breaking changes require
a 2.0.0.

### Added
- `rest_server.__version__`, surfaced by `GET /` and the OpenAPI schema, so a deployed instance
  can report its release version.

### Changed
- **Breaking:** the backend moved from Neo4j (v0.2.0) to PostgreSQL, with a new API surface
  under `/v1/assets/*` and the `/modelcards` / `/datasheets` read endpoints. There is no
  automated Neo4j-to-PostgreSQL data migration.

### Removed
- Repo hygiene: dropped a committed demo CSV export (`model_cards 2026-05-17 12-37-00.csv`) and
  working notes (`dev_log.md`) that shouldn't ship in a 1.0.0 tree.

### Known limitations
- `legacy/` (Flask + Neo4j REST server) and `mcp_server/` are retained in-repo for reference
  only and are **not supported** under 1.0.0; bugs filed against them will not be treated as
  1.0.x regressions. CI no longer installs or tests `mcp_server/`'s dependencies.
- `mcp_server/`'s `mcp` dependency has 6 open high-severity Dependabot advisories (WebSocket
  Host/Origin validation, HTTP session-request authentication, DNS rebinding protection). Since
  `mcp_server/` is archive-only and excluded from the 1.0.0 support contract, these are not
  fixed in this release — do not run `mcp_server/` against untrusted networks.
- Model similarity requires an OpenAI API key and is off by default
  (`ENABLE_MC_SIMILARITY=False`).
- Bulk ingest is partial-success: each item in a bulk request is validated and inserted
  independently, so a `200 OK` may still contain per-item errors in `results`.

## [v0.2.0] - 2025-06-10

### Added
- API Endpoints:
  - `/get_github_credentials` (GET): Retrieve GitHub username and token.
  - `/get_huggingface_credentials` (GET): Retrieve Hugging Face username and token.
  - `/modelcard_linkset` (HEAD): Provides model card linkset relations in the HTTP Link header for improved discoverability and interoperability.
- New Project Logo

### Changed
  - Integration guides for OpenAI, Hugging Face, and GitHub.
