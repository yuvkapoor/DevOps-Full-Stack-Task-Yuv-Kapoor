# DevOps-Full-Stack-Task-Yuv-Kapoor
# SupaChat

SupaChat is a full-stack conversational analytics app built on top of Supabase PostgreSQL. It lets users ask blog analytics questions in plain English, translates them into database queries through an MCP-style execution flow, and returns chatbot answers, tables, and Recharts visualizations.

This project also takes the app through the full DevOps lifecycle: Dockerization, reverse proxying with Nginx, CI/CD with GitHub Actions, deployment to a public Linux VM, and observability with Prometheus, Grafana, Loki, cAdvisor, and node-exporter.

Note: the original task mentioned AWS EC2. This implementation uses an Azure Ubuntu VM with the same production deployment pattern.

## Live URLs

- App: `http://98.70.25.190/`
- Health: `http://98.70.25.190/health`
- Grafana: `http://98.70.25.190:3001`
- Prometheus: `http://98.70.25.190:9090`
- Loki API: `http://98.70.25.190:3100`

## Architecture

```text
Browser
  -> Nginx reverse proxy
     -> Frontend (React + Vite + Recharts)
     -> Backend API (FastAPI)
        -> MCP execution path
        -> Supabase PostgreSQL
        -> Gemini fallback / planner
        -> DevOps Agent endpoints

Observability
  -> Prometheus scrapes backend metrics, cAdvisor, node-exporter
  -> Grafana visualizes Prometheus + Loki data
  -> Promtail ships Docker/container logs to Loki
```

## Features

- Natural language analytics queries against Supabase PostgreSQL
- Chatbot response with generated SQL, chart, and result table
- Query history
- FastAPI `/health` endpoint
- MCP-style SQL execution endpoint
- Gemini-backed dynamic planner and non-DB fallback
- Docker Compose stack with health checks and resource limits
- Nginx reverse proxy for `/` and `/api`
- GitHub Actions CI/CD pipeline
- Monitoring and logging stack
- Bonus DevOps Agent for diagnosis, restarts, deploy trigger, log summarization, and CI failure explanation

## Tech Stack

- Frontend: React, Vite, Axios, Recharts
- Backend: FastAPI, httpx, Prometheus Instrumentator
- Database: Supabase PostgreSQL
- AI: Gemini API, optional Anthropic fallback
- Infra: Docker, Docker Compose, Nginx
- CI/CD: GitHub Actions, GHCR, SSH deploy
- Monitoring: Prometheus, Grafana, Loki, Promtail, cAdvisor, node-exporter

## Repository Structure

- [frontend/src/app.jsx](d:\work\Supachat\frontend\src\app.jsx): main chat UI and DevOps Agent launcher
- [backend/main.py](d:\work\Supachat\backend\main.py): chat API, health endpoint, MCP endpoint, DevOps Agent endpoints
- [docker-compose.yml](d:\work\Supachat\docker-compose.yml): runtime stack
- [docker-compose.build.yml](d:\work\Supachat\docker-compose.build.yml): local image build overrides
- [infra/nginx/nginx.conf](d:\work\Supachat\infra\nginx\nginx.conf): reverse proxy, gzip, caching
- [infra/prometheus/prometheus.yml](d:\work\Supachat\infra\prometheus\prometheus.yml): scrape config
- [infra/grafana/dashboards/supachat-observability.json](d:\work\Supachat\infra\grafana\dashboards\supachat-observability.json): prebuilt dashboard
- [.github/workflows/ci-cd.yml](d:\work\Supachat\.github\workflows\ci-cd.yml): CI/CD pipeline
- [scripts/bootstrap-ubuntu.sh](d:\work\Supachat\scripts\bootstrap-ubuntu.sh): Docker bootstrap for Ubuntu
- [scripts/run-linux-build.sh](d:\work\Supachat\scripts\run-linux-build.sh): first-time Linux build
- [scripts/deploy-azure.sh](d:\work\Supachat\scripts\deploy-azure.sh): image-based deployment script

## Local Setup

### 1. Backend environment

Use [backend/.env.example](d:\work\Supachat\backend\.env.example) as the template.

Required values:

- `DATABASE_URL`
- `SUPABASE_PROJECT_ID`
- `SUPABASE_PROJECT_URL`
- `SUPABASE_API_KEY`
- `SUPABASE_ANON_KEY`

Optional values:

- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`
- `DEVOPS_AGENT_TOKEN`
- `GITHUB_REPO`
- `GITHUB_ACTIONS_TOKEN`

### 2. Compose environment

Use [.env.compose.example](d:\work\Supachat\.env.compose.example) as the template.

This controls:

- published ports
- image names
- Grafana bootstrap credentials
- MCP timeout

### 3. Run locally on Ubuntu/Linux

```bash
cp backend/.env.example backend/.env
cp .env.compose.example .env.compose
bash scripts/bootstrap-ubuntu.sh
bash scripts/run-linux-build.sh
```

## Docker and Deployment

The production stack contains:

- `frontend`
- `backend`
- `mcp-server`
- `nginx`
- `prometheus`
- `grafana`
- `loki`
- `promtail`
- `cadvisor`
- `node-exporter`

Key production characteristics:

- container health checks
- CPU and memory limits
- environment-based configuration
- reproducible deployment through Docker Compose
- public access through Nginx

### Reverse Proxy

[infra/nginx/nginx.conf](d:\work\Supachat\infra\nginx\nginx.conf) provides:

- `/` -> frontend
- `/api/` -> backend
- `/health` -> backend health endpoint
- `gzip`
- caching for static assets
- websocket-ready upgrade headers

## CI/CD

The GitHub Actions workflow is defined in [.github/workflows/ci-cd.yml](d:\work\Supachat\.github\workflows\ci-cd.yml).

Pipeline stages:

1. `validate`
   - checkout
   - backend dependency install
   - backend syntax check
   - frontend dependency install
   - frontend production build
   - Docker Compose validation
2. `build-and-push`
   - build backend and frontend images
   - push images to GitHub Container Registry
3. `deploy-azure-vm`
   - SSH into Azure Ubuntu VM
   - sync repository state to `main`
   - log in to GHCR
   - deploy latest images with [scripts/deploy-azure.sh](d:\work\Supachat\scripts\deploy-azure.sh)
   - wait for healthy services

### Required GitHub Secrets

- `AZURE_VM_HOST`
- `AZURE_VM_USER`
- `AZURE_VM_SSH_PORT`
- `AZURE_VM_APP_DIR`
- `AZURE_VM_SSH_KEY`
- `GHCR_PAT`

## Monitoring and Dashboards

Monitoring stack:

- Prometheus for metrics collection
- Grafana for dashboards
- Loki for log storage
- Promtail for log shipping
- cAdvisor for container metrics
- node-exporter for host metrics

Prometheus scrapes:

- backend `/metrics`
- Prometheus self-metrics
- cAdvisor
- node-exporter

Grafana is pre-provisioned with:

- Prometheus datasource
- Loki datasource
- SupaChat dashboard provider

Dashboard coverage includes:

- CPU usage
- memory usage
- container health
- request latency
- application logs
- error logs

## DevOps Agent Bonus

The bonus DevOps Agent is exposed through backend APIs and a frontend modal.

Available actions:

- stack diagnosis
- restart selected service
- summarize logs
- explain CI/CD failure logs
- trigger deployment

Relevant API endpoints:

- `GET /api/devops/diagnose`
- `POST /api/devops/logs`
- `POST /api/devops/restart`
- `POST /api/devops/deploy`
- `POST /api/devops/explain-ci`

Security:

- protected with `DEVOPS_AGENT_TOKEN`
- trigger deploy additionally needs `GITHUB_ACTIONS_TOKEN`

## AI Tools Used

- GPT-based coding assistance for implementation, debugging, DevOps setup, and UI iteration
- Gemini API for dynamic query planning and non-database conversational fallback
- AI-assisted RCA flow for the DevOps Agent CI/log explanation feature

## Submission Notes

This project satisfies the task goals with:

- deployed full-stack analytics app
- chatbot plus tables and charts
- Dockerized services
- reverse proxy via Nginx
- CI/CD pipeline
- monitoring stack
- bonus DevOps Agent
