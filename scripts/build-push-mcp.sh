#!/usr/bin/env bash
# Build and push the Patra MCP image, then optionally restart the patramcp pod.
# Run from repo root. Requires docker login to push.
set -euo pipefail
cd "$(dirname "$0")/.."

# Load local environment (not committed to git) if present.
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a
  source .env
  set +a
fi

IMAGE="${IMAGE:-plalelab/patra-mcp:latest}"
POD_ID="${POD_ID:-patramcp}"

echo "Building $IMAGE ..."
docker build -f mcp_server/Dockerfile -t "$IMAGE" .
echo "Pushing $IMAGE ..."
docker push "$IMAGE"
echo "Done: $IMAGE"

# Optionally restart the MCP pod via Tapis Pods API.
# Requires .env with: TAPIS_PODS_BASE_URL, TAPIS_USERNAME, TAPIS_PASSWORD
# Uses tapipy from a dedicated venv at ~/.venvs/tapis.
# Create it once with:
#   python3 -m venv ~/.venvs/tapis && ~/.venvs/tapis/bin/pip install --upgrade pip tapipy
TAPIS_VENV="${TAPIS_VENV:-$HOME/.venvs/tapis}"
TAPIS_PODS_BASE_URL="${TAPIS_PODS_BASE_URL:-}"

if [[ -n "$TAPIS_PODS_BASE_URL" && -n "${TAPIS_USERNAME:-}" && -n "${TAPIS_PASSWORD:-}" ]]; then
  if [[ ! -x "$TAPIS_VENV/bin/python3" ]]; then
    echo "ERROR: tapipy venv not found at $TAPIS_VENV" >&2
    echo "  Create it with: python3 -m venv $TAPIS_VENV && $TAPIS_VENV/bin/pip install --upgrade pip tapipy" >&2
    exit 1
  fi

  echo "Restarting Tapis Pod: $POD_ID ..."
  "$TAPIS_VENV/bin/python3" << 'PY'
import os
from tapipy.tapis import Tapis

t = Tapis(
    base_url=os.environ["TAPIS_PODS_BASE_URL"],
    username=os.environ["TAPIS_USERNAME"],
    password=os.environ["TAPIS_PASSWORD"],
)
t.get_tokens()
print("Authenticated as", os.environ["TAPIS_USERNAME"])

pod_id = os.environ.get("POD_ID", "patramcp")
result = t.pods.restart_pod(pod_id=pod_id)
status = getattr(result, "status_requested", "unknown")
print(f"  {pod_id}: restart requested (status_requested={status})")
print("Done restarting pod.")
PY
else
  echo "TAPIS_PODS_BASE_URL / TAPIS_USERNAME / TAPIS_PASSWORD not set; skipping pod restart." >&2
fi
