# SupaChat Dockerization (Ubuntu VM)
#Pipeline automate testing via linux vm terminal
This guide covers only:
- Dockerization
- Nginx reverse proxy
- Monitoring stack (Prometheus, Grafana, Loki, Promtail)

## 1) Prerequisites on Ubuntu VM

```bash
cd /path/to/Supachat
bash scripts/bootstrap-ubuntu.sh
```

Then reconnect SSH (or log out/in), and verify:

```bash
docker --version
docker compose version
```

## 2) Configure Environment Files

### Backend runtime vars

Use your real values:

```bash
cp backend/.env.example backend/.env
nano backend/.env
```

### Compose runtime vars (ports, Grafana credentials)

```bash
cp .env.compose.example .env.compose
nano .env.compose
```

## 3) Build and Run (App + Nginx + Monitoring)

```bash
docker compose --env-file .env.compose --compatibility -f docker-compose.yml -f docker-compose.build.yml up -d --build
docker compose --env-file .env.compose --compatibility -f docker-compose.yml ps
```

## 4) Access URLs

Replace `<VM_PUBLIC_IP>` with your Azure VM public IP:

- App (Nginx reverse proxy): `http://<VM_PUBLIC_IP>/`
- Backend health via Nginx: `http://<VM_PUBLIC_IP>/health`
- Prometheus: `http://<VM_PUBLIC_IP>:9090`
- Grafana: `http://<VM_PUBLIC_IP>:3001`

`cAdvisor` and `node-exporter` are internal-only and scraped by Prometheus over the Docker network.

Grafana default credentials come from `.env.compose`.

## 5) Azure NSG Ports to Open

- `80` (application)
- `9090` (Prometheus)
- `3001` (Grafana)

If you want fewer public ports, keep only `80` and access monitoring through SSH tunneling.

## 6) What This Stack Includes

- `frontend` container: static React build
- `backend` container: FastAPI app
- `mcp-server` container: MCP endpoint for SQL tool calls
- `nginx` container:
  - `/` -> frontend
  - `/api` -> backend
  - gzip enabled
  - static caching enabled
  - websocket headers enabled for `/api`
- Monitoring:
  - Prometheus
  - Grafana (with pre-provisioned Prometheus + Loki datasources)
  - Loki
  - Promtail
  - cAdvisor
  - Node Exporter

## 7) Operations Commands

Start/Update:

```bash
docker compose --env-file .env.compose --compatibility -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

Logs:

```bash
docker compose --env-file .env.compose -f docker-compose.yml logs -f backend nginx
```

Safe rolling restart of app edge/services:

```bash
bash scripts/restart-safe.sh
```

Stop stack:

```bash
docker compose --env-file .env.compose -f docker-compose.yml down
```

Stop and remove volumes:

```bash
docker compose --env-file .env.compose -f docker-compose.yml down -v
```
