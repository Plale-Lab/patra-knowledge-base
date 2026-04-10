#!/usr/bin/env bash
# Common build/push/restart logic for Patra images.
#
# This script is meant to be called by thin wrappers that only set:
# - IMAGE: Docker image (including tag)
# - DOCKERFILE: path to Dockerfile (optional if building via CONTEXT_DIR/Dockerfile)
# - CONTEXT_DIR: docker build context directory (default: repo root)
# - PODS: space-separated pod ids to restart
set -euo pipefail

cd "$(dirname "$0")/.."

# Load local environment (not committed to git) if present.
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a
  source .env
  set +a
fi

IMAGE="${IMAGE:-}"
DOCKERFILE="${DOCKERFILE:-}"
CONTEXT_DIR="${CONTEXT_DIR:-.}"
PODS="${PODS:-}"

if [[ -z "$IMAGE" ]]; then
  echo "ERROR: IMAGE is required (e.g. plalelab/patra-backend:latest)" >&2
  exit 2
fi

if [[ ! -d "$CONTEXT_DIR" ]]; then
  echo "ERROR: CONTEXT_DIR not found: $CONTEXT_DIR" >&2
  exit 2
fi

if [[ -n "$DOCKERFILE" ]]; then
  if [[ ! -f "$DOCKERFILE" ]]; then
    echo "ERROR: DOCKERFILE not found: $DOCKERFILE" >&2
    exit 2
  fi
  echo "Building $IMAGE (dockerfile: $DOCKERFILE, context: $CONTEXT_DIR) ..."
  docker build -f "$DOCKERFILE" -t "$IMAGE" "$CONTEXT_DIR"
else
  if [[ ! -f "$CONTEXT_DIR/Dockerfile" ]]; then
    echo "ERROR: DOCKERFILE not set and no Dockerfile at $CONTEXT_DIR/Dockerfile" >&2
    exit 2
  fi
  echo "Building $IMAGE (dockerfile: $CONTEXT_DIR/Dockerfile, context: $CONTEXT_DIR) ..."
  docker build -t "$IMAGE" "$CONTEXT_DIR"
fi

echo "Pushing $IMAGE ..."
docker push "$IMAGE"
echo "Done: $IMAGE"

if [[ -z "$PODS" ]]; then
  echo "No PODS set; skipping restarts." >&2
  exit 0
fi

TAPIS_VENV="${TAPIS_VENV:-$HOME/.venvs/tapis}"
TAPIS_PODS_BASE_URL="${TAPIS_PODS_BASE_URL:-}"

if [[ -z "$TAPIS_PODS_BASE_URL" || -z "${TAPIS_USERNAME:-}" || -z "${TAPIS_PASSWORD:-}" ]]; then
  echo "TAPIS_PODS_BASE_URL / TAPIS_USERNAME / TAPIS_PASSWORD not set; skipping pod restarts." >&2
  exit 0
fi

if [[ ! -x "$TAPIS_VENV/bin/python3" ]]; then
  echo "ERROR: tapipy venv not found at $TAPIS_VENV" >&2
  echo "  Create it with: python3 -m venv $TAPIS_VENV && $TAPIS_VENV/bin/pip install --upgrade pip tapipy" >&2
  exit 1
fi

echo "Restarting pods via Tapis Pods API:"
printf '  - %s\n' $PODS

TAPIS_PODS_BASE_URL="$TAPIS_PODS_BASE_URL" \
TAPIS_USERNAME="$TAPIS_USERNAME" \
TAPIS_PASSWORD="$TAPIS_PASSWORD" \
PODS="$PODS" \
"$TAPIS_VENV/bin/python3" <<'PY'
import os, sys
from tapipy.tapis import Tapis

t = Tapis(
    base_url=os.environ["TAPIS_PODS_BASE_URL"],
    username=os.environ["TAPIS_USERNAME"],
    password=os.environ["TAPIS_PASSWORD"],
)
t.get_tokens()
print("Authenticated as", os.environ["TAPIS_USERNAME"])

pods = os.environ.get("PODS", "").split()
if not pods:
    print("No PODS provided; nothing to restart.", file=sys.stderr)
    raise SystemExit(2)

failed = 0
for pod_id in pods:
    try:
        result = t.pods.restart_pod(pod_id=pod_id)
        status = getattr(result, "status_requested", "unknown")
        print(f"  {pod_id}: restart requested (status_requested={status})")
    except Exception as exc:
        failed += 1
        print(f"  {pod_id}: FAILED — {exc}", file=sys.stderr)

if failed:
    raise SystemExit(1)
print("Done restarting pods.")
PY

