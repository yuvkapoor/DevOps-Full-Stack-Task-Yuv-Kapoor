#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE_ARGS=()
if [[ -f ".env.compose" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env.compose"
  set +a
  ENV_FILE_ARGS=(--env-file .env.compose)
fi

echo "[1/3] Building and starting SupaChat stack..."
docker compose "${ENV_FILE_ARGS[@]}" --compatibility -f docker-compose.yml -f docker-compose.build.yml up -d --build

echo "[2/3] Active services:"
docker compose "${ENV_FILE_ARGS[@]}" --compatibility -f docker-compose.yml ps

echo "[3/3] Health endpoint:"
curl -fsS "http://127.0.0.1:${NGINX_HTTP_PORT:-80}/health" | sed 's/.*/&\n/'

echo "SupaChat is live at: http://<your-vm-public-ip>:${NGINX_HTTP_PORT:-80}"
