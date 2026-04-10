#!/usr/bin/env bash
#
# Generic wrapper. Set IMAGE/DOCKERFILE/PODS (and optionally CONTEXT_DIR) as needed.
#
# Examples:
#   ./scripts/build-push-restart.sh
#   IMAGE=plalelab/patra-mcp:latest DOCKERFILE=mcp_server/Dockerfile PODS="patramcp" ./scripts/build-push-restart.sh
set -euo pipefail

IMAGE="${IMAGE:-plalelab/patra-backend:latest}"
DOCKERFILE="${DOCKERFILE:-rest_server/Dockerfile}"
CONTEXT_DIR="${CONTEXT_DIR:-.}"
PODS="${PODS:-patradb patradbeaver patrabackend patra patra-dev}"

exec "$(dirname "$0")/build-push-restart-common.sh"

