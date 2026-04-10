# SupaChat CI/CD (GitHub Actions -> Azure VM)

This pipeline validates the app, builds Docker images, pushes them to GHCR, and deploys them to your Ubuntu VM.

## Workflow file

- `.github/workflows/ci-cd.yml`

## What the pipeline does

1. Validates backend Python imports/compilation
2. Builds the frontend production bundle
3. Validates Docker Compose configuration
4. Builds and pushes:
   - `ghcr.io/<owner>/supachat-backend:<commit-sha>`
   - `ghcr.io/<owner>/supachat-backend:latest`
   - `ghcr.io/<owner>/supachat-frontend:<commit-sha>`
   - `ghcr.io/<owner>/supachat-frontend:latest`
5. SSHes into the Azure VM
6. Pulls the latest images
7. Recreates the Docker Compose stack
8. Waits for core services to become healthy
9. Verifies app and monitoring health endpoints

## GitHub Secrets to add

- `AZURE_VM_HOST`
  - Example: `98.70.25.190`
- `AZURE_VM_USER`
  - Example: your Ubuntu username
- `AZURE_VM_SSH_KEY`
  - Private SSH key content for the VM
- `AZURE_VM_SSH_PORT`
  - Usually `22`
- `AZURE_VM_APP_DIR`
  - Example: `/home/<your-user>/Supachat`
- `GHCR_PAT`
  - GitHub Personal Access Token with package read access on deploy

## First-time VM requirements

The VM must already have:

- Docker + Docker Compose installed
- the SupaChat project present at `AZURE_VM_APP_DIR`
- `backend/.env` created with your real secrets
- `.env.compose` created with your runtime ports and Grafana creds

If the VM project folder contains `.git`, deploy will sync `main` before rollout.
If the VM folder was drag-dropped without `.git`, deploy still works and uses the files already on the VM.

## Triggering deployment

- push to `main`, or
- run the workflow manually from GitHub Actions

## Recommended GHCR package visibility

If deployment pulls from GHCR on the VM, keep the packages accessible to the account used by `GHCR_PAT`.
