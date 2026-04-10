#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE_ARGS=()
if [[ -f ".env.compose" ]]; then
  ENV_FILE_ARGS=(--env-file .env.compose)
fi

wait_for_healthy() {
  local service="$1"
  local timeout="${2:-90}"
  local start_ts
  start_ts="$(date +%s)"

  while true; do
    local cid
    cid="$(docker compose "${ENV_FILE_ARGS[@]}" -f docker-compose.yml ps -q "$service")"
    if [[ -n "$cid" ]]; then
      local health
      health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}running{{end}}' "$cid" 2>/dev/null || true)"
      if [[ "$health" == "healthy" || "$health" == "running" ]]; then
        echo "Service '$service' is healthy."
        return 0
      fi
    fi

    if (( $(date +%s) - start_ts > timeout )); then
      echo "Timeout waiting for '$service' to become healthy."
      return 1
    fi
    sleep 2
  done
}

echo "Rolling restart with health checks..."
for svc in mcp-server backend frontend nginx; do
  echo "Restarting $svc..."
  docker compose "${ENV_FILE_ARGS[@]}" --compatibility -f docker-compose.yml up -d --no-deps "$svc"
  wait_for_healthy "$svc"
done

echo "Safe restart completed."
