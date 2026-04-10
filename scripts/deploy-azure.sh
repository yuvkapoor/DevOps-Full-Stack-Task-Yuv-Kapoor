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
  local timeout="${2:-120}"
  local start_ts
  start_ts="$(date +%s)"

  while true; do
    local cid
    cid="$(docker compose "${ENV_FILE_ARGS[@]}" -f docker-compose.yml ps -q "$service")"
    if [[ -n "$cid" ]]; then
      local status
      status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)"
      if [[ "$status" == "healthy" || "$status" == "running" ]]; then
        echo "Service '$service' is ready."
        return 0
      fi
    fi

    if (( $(date +%s) - start_ts > timeout )); then
      echo "Timed out waiting for '$service' to become ready."
      docker compose "${ENV_FILE_ARGS[@]}" -f docker-compose.yml ps
      return 1
    fi
    sleep 3
  done
}

if [[ -z "${BACKEND_IMAGE:-}" || -z "${FRONTEND_IMAGE:-}" ]]; then
  echo "BACKEND_IMAGE and FRONTEND_IMAGE must be set for image-based deployment."
  exit 1
fi

export MCP_IMAGE="${MCP_IMAGE:-$BACKEND_IMAGE}"

echo "[1/4] Pull latest images..."
docker compose "${ENV_FILE_ARGS[@]}" --compatibility -f docker-compose.yml pull

echo "[2/4] Recreate app + observability services..."
docker compose "${ENV_FILE_ARGS[@]}" --compatibility -f docker-compose.yml up -d --remove-orphans

echo "[3/4] Waiting for core services..."
for svc in mcp-server backend frontend nginx; do
  wait_for_healthy "$svc"
done

curl -fsS http://127.0.0.1/health >/dev/null
curl -fsS http://127.0.0.1:9090/-/healthy >/dev/null
curl -fsS http://127.0.0.1:3001/api/health >/dev/null

echo "[4/4] Service status:"
docker compose "${ENV_FILE_ARGS[@]}" --compatibility -f docker-compose.yml ps

echo "[5/5] Pruning old dangling images..."
docker image prune -f
