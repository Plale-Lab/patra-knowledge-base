#!/usr/bin/env bash
# Build and push the Patra frontend image to Docker Hub, then restart the patra pod.
#
# Defaults:
#   IMAGE=plalelab/patra-frontend:latest
#   FRONTEND_DIR=../patra-frontend   (sibling repo)
#   POD_ID=patra
#
# Requires:
# - docker login (for push)
# - .env (optional) with TAPIS_PODS_BASE_URL, TAPIS_USERNAME, TAPIS_PASSWORD (for restart)
# - tapipy venv (same convention as other scripts): ~/.venvs/tapis
set -euo pipefail

# Ensure we're running from patra-kg repo root.
cd "$(dirname "$0")/.."

# Load local environment (not committed to git) if present.
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a
  source .env
  set +a
fi

IMAGE="${IMAGE:-plalelab/patra-frontend:latest}"
FRONTEND_DIR="${FRONTEND_DIR:-../patra-frontend}"
POD_ID="${POD_ID:-patra}"

if [[ ! -d "$FRONTEND_DIR" ]]; then
  echo "ERROR: FRONTEND_DIR not found: $FRONTEND_DIR" >&2
  echo "  Set FRONTEND_DIR to your patra-frontend checkout path." >&2
  exit 1
fi

if [[ ! -f "$FRONTEND_DIR/Dockerfile" ]]; then
  echo "ERROR: Dockerfile not found in FRONTEND_DIR: $FRONTEND_DIR/Dockerfile" >&2
  exit 1
fi

echo "Building $IMAGE (context: $FRONTEND_DIR, dockerfile: $FRONTEND_DIR/Dockerfile) ..."
docker build -t "$IMAGE" "$FRONTEND_DIR"

echo "Pushing $IMAGE ..."
docker push "$IMAGE"
echo "Done: $IMAGE"

# Restart the patra pod via Tapis Pods API (optional).
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

pod_id = os.environ.get("POD_ID", "patra")
result = t.pods.restart_pod(pod_id=pod_id)
status = getattr(result, "status_requested", "unknown")
print(f"  {pod_id}: restart requested (status_requested={status})")
print("Done restarting pod.")
PY
else
  echo "TAPIS_PODS_BASE_URL / TAPIS_USERNAME / TAPIS_PASSWORD not set; skipping pod restart." >&2
fi

