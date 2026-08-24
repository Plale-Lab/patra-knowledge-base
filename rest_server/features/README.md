# Backend Feature Modules

This directory groups PATRA backend logic by feature instead of keeping all feature-specific code directly under `routes/`.

Current modules:
- `ask_patra`: conversational assistant service, prompts, and models
- `automated_ingestion`: isolated CSV ingestion pipeline
- `hf_import`: fetches a public Hugging Face model/dataset repo and normalizes it into flat Submit-form fields
- `agent_toolkit`: schema-search-oriented AI tooling docs and support files
- `resource_records`: record editing/search domain docs
- `shared`: reusable OpenAI-compatible provider helpers
- `weekly_report`: periodic (weekly) reporting of aggregate model-card/datasheet counts to an external webhook (Carlos's services-reporting board)

HTTP entrypoints still live under `rest_server/routes/` and import from these feature modules.
