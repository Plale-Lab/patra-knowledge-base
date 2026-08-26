#!/usr/bin/env python3
"""Export the active FastAPI backend's OpenAPI spec to docs/patra_openapi.json.

Enables all optional feature-flagged routers so the exported spec documents
the full endpoint surface, not just whatever's active in one environment.
"""

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ["ENABLE_ASK_PATRA"] = "true"
os.environ["ENABLE_DOMAIN_EXPERIMENTS"] = "true"
os.environ["ENABLE_HF_IMPORT"] = "true"

from rest_server.main import app  # noqa: E402  (must import after env vars/sys.path are set)

OUTPUT_PATH = REPO_ROOT / "docs" / "patra_openapi.json"


def main() -> None:
    schema = app.openapi()
    OUTPUT_PATH.write_text(json.dumps(schema, indent=2) + "\n")
    print(f"Wrote OpenAPI spec to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
