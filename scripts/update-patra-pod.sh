#!/usr/bin/env bash
# Update the patra pod definition from k8s/patra.json via Tapis Pods API.
# Run from repo root.
set -euo pipefail
cd "$(dirname "$0")/.."

# Load local environment (not committed to git) if present.
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a
  source .env
  set +a
fi

TAPIS_VENV="${TAPIS_VENV:-$HOME/.venvs/tapis}"
TAPIS_PODS_BASE_URL="${TAPIS_PODS_BASE_URL:-}"
POD_SPEC_PATH="${POD_SPEC_PATH:-k8s/patra.json}"
POD_ID_OVERRIDE="${POD_ID:-}"
RESTART_AFTER_UPDATE="${RESTART_AFTER_UPDATE:-true}"

if [[ -z "$TAPIS_PODS_BASE_URL" || -z "${TAPIS_USERNAME:-}" || -z "${TAPIS_PASSWORD:-}" ]]; then
  echo "ERROR: TAPIS_PODS_BASE_URL, TAPIS_USERNAME, and TAPIS_PASSWORD are required." >&2
  exit 1
fi

if [[ ! -x "$TAPIS_VENV/bin/python3" ]]; then
  echo "ERROR: tapipy venv not found at $TAPIS_VENV" >&2
  echo "  Create it with: python3 -m venv $TAPIS_VENV && $TAPIS_VENV/bin/pip install --upgrade pip tapipy" >&2
  exit 1
fi

if [[ ! -f "$POD_SPEC_PATH" ]]; then
  echo "ERROR: pod spec file not found: $POD_SPEC_PATH" >&2
  exit 1
fi

echo "Updating pod spec from $POD_SPEC_PATH ..."

TAPIS_PODS_BASE_URL="$TAPIS_PODS_BASE_URL" \
TAPIS_USERNAME="$TAPIS_USERNAME" \
TAPIS_PASSWORD="$TAPIS_PASSWORD" \
POD_SPEC_PATH="$POD_SPEC_PATH" \
POD_ID="$POD_ID_OVERRIDE" \
RESTART_AFTER_UPDATE="$RESTART_AFTER_UPDATE" \
KEEP_PROXY="${KEEP_PROXY:-false}" \
"$TAPIS_VENV/bin/python3" << 'PY'
import json
import os
import sys

# tapipy uses requests; disable proxy env by default to avoid tunnel failures in
# locked-down environments. Set KEEP_PROXY=true to preserve proxy variables.
keep_proxy = os.environ.get("KEEP_PROXY", "false").strip().lower() == "true"
if not keep_proxy:
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "all_proxy",
    ):
        os.environ.pop(key, None)

from tapipy.tapis import Tapis

spec_path = os.environ["POD_SPEC_PATH"]
pod_id_override = os.environ.get("POD_ID", "").strip()
restart_after_update = os.environ.get("RESTART_AFTER_UPDATE", "true").strip().lower() == "true"

with open(spec_path, "r", encoding="utf-8") as f:
    raw_spec = json.load(f)

pod_id = pod_id_override or raw_spec.get("pod_id")
if not pod_id:
    raise RuntimeError("pod_id missing (set POD_ID or include pod_id in spec file)")

# Keep only fields meant for user-managed pod definitions.
allowed_keys = {
    "image",
    "template",
    "description",
    "environment_variables",
    "secret_map",
    "status_requested",
    "volume_mounts",
    "time_to_stop_default",
    "networking",
    "resources",
    "compute_queue",
    "command",
    "arguments",
}
payload = {k: v for k, v in raw_spec.items() if k in allowed_keys}

t = Tapis(
    base_url=os.environ["TAPIS_PODS_BASE_URL"],
    username=os.environ["TAPIS_USERNAME"],
    password=os.environ["TAPIS_PASSWORD"],
)
t.get_tokens()
print("Authenticated as", os.environ["TAPIS_USERNAME"])

errors = []
update_result = None

# tapipy signatures can vary by version, so try common call styles.
for style in ("kwargs", "pod_definition", "req_body"):
    try:
        if style == "kwargs":
            update_result = t.pods.update_pod(pod_id=pod_id, **payload)
        elif style == "pod_definition":
            update_result = t.pods.update_pod(pod_id=pod_id, pod_definition=payload)
        else:
            update_result = t.pods.update_pod(pod_id=pod_id, req_body=payload)
        print(f"Updated pod '{pod_id}' using style={style}")
        break
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{style}: {exc}")

if update_result is None:
    print("Failed to update pod. Tried call styles:", file=sys.stderr)
    for item in errors:
        print(f"  - {item}", file=sys.stderr)
    raise RuntimeError(f"Unable to update pod '{pod_id}'")

status_requested = getattr(update_result, "status_requested", "unknown")
print(f"Update response status_requested={status_requested}")

if restart_after_update:
    restart_result = t.pods.restart_pod(pod_id=pod_id)
    restart_status = getattr(restart_result, "status_requested", "unknown")
    print(f"Restart requested for '{pod_id}' (status_requested={restart_status})")

print("Done.")
PY

