# Deployment & Container Shell Guide

This document outlines the containerization strategy, build procedures, and runtime configuration for AI Travel Concierge. In Phase 1, container build definitions are provided as a local deployment shell only; no cloud deployment, hosting provider, or remote deployment pipeline is configured.

---

## 1. Container Architecture Overview

Both services are containerized using minimal, security-hardened Dockerfiles:

| Service | Base Image | Multi-Stage | Non-Root User | Standalone Output | Build Arguments |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Backend** (`backend/Dockerfile`) | `python:3.11-slim` | No | `appuser:appgroup` (UID 1001) | N/A | None |
| **Frontend** (`frontend/Dockerfile`) | `node:20-alpine` | Yes (deps, builder, runner) | `nextjs:nodejs` (UID 1001) | Yes (`output: "standalone"`) | `NEXT_PUBLIC_API_BASE_URL` |

### Security & Hygiene Rules
- **No Secrets in Images**: Never copy `.env` or `.env.*` files into container images. All runtime configurations must be injected at container startup.
- **Non-Root Execution**: Both containers run under unprivileged, non-root user accounts (`appuser` and `nextjs`).
- **Production Dependencies Only**: The backend image installs only `requirements.txt` (excluding `pytest`, `ruff`, and development tooling).
- **Standalone Tracing**: The frontend leverages Next.js standalone output tracing to package only required dependencies, keeping the image size lean (~73 MB compressed).

---

## 2. Building Images Locally

### 1. Build the Backend Image

From the repository root:
```bash
docker build -t atc-backend:local backend
```

### 2. Build the Frontend Image

Next.js embeds public environment variables (`NEXT_PUBLIC_*`) into static bundles during compilation. Therefore, `NEXT_PUBLIC_API_BASE_URL` must be passed as a build argument:

```bash
docker build -t atc-frontend:local \
  --build-arg NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 \
  frontend
```

---

## 3. Running Containers Locally

### 1. Run the Backend Container

```bash
docker run --rm -d \
  --name atc-backend \
  -p 8000:8000 \
  -e APP_ENV=development \
  -e CORS_ORIGINS='["http://localhost:3000"]' \
  atc-backend:local
```

Verify backend health:
```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/api/version
```

### 2. Run the Frontend Container

```bash
docker run --rm -d \
  --name atc-frontend \
  -p 3000:3000 \
  atc-frontend:local
```

Verify frontend responsiveness:
```powershell
Invoke-WebRequest -Uri http://localhost:3000 -UseBasicParsing
```

### 3. Stop Containers

```bash
docker stop atc-backend atc-frontend
```

---

## 4. Runtime Environment Variables

Runtime configuration must be supplied via container environment variables or orchestration secrets.

### Backend (`atc-backend:local`)

| Variable | Required | Default | Description |
| :--- | :---: | :--- | :--- |
| `APP_ENV` | No | `development` | Environment label (`development`, `test`, `production`). |
| `CORS_ORIGINS` | No | `["http://localhost:3000", ...]` | Allowed origins for cross-origin requests. |
| `DATABASE_URL` | No | `None` | Optional PostgreSQL connection string (`postgresql+psycopg://...`). Unset by default. |

### Frontend (`atc-frontend:local`)

| Variable | Scope | Default | Description |
| :--- | :---: | :--- | :--- |
| `NEXT_PUBLIC_API_BASE_URL` | **Build-Time** | `http://localhost:8000` | Backend API URL embedded into browser JavaScript bundles during `docker build`. |
| `PORT` | Runtime | `3000` | Port on which the standalone Node.js server listens. |
| `HOSTNAME` | Runtime | `0.0.0.0` | Host interface binding for container networking. |

---

## 5. What is NOT Covered in Phase 1

This container shell intentionally excludes production hosting and infrastructure automation:
- **No Hosting Provider Selected**: No cloud vendor (AWS, GCP, Azure, Fly.io, Railway, etc.) or container orchestrator (Kubernetes, ECS, Nomad) is configured.
- **No TLS / SSL Termination**: Containers serve plain HTTP (ports 8000 and 3000). A production ingress, reverse proxy, or load balancer must terminate HTTPS.
- **No Secrets Management**: No integration with external secret vaults (HashiCorp Vault, AWS Secrets Manager, GCP Secret Manager, Doppler).
- **No CI/CD Deployment**: CI workflows run automated tests and linters only. Automated pushing to container registries or automated CD triggers are not implemented.
- **No Booking Engine Logic**: The application remains strictly a travel discovery assistant, with no payment gateways or reservation transaction systems.

---

## 6. Pre-Deployment Decision Checklist

Before planning a real production deployment, the engineering team must answer these key questions:

1. **Target Runtime Platform**:
   - Will the application run on managed serverless containers (e.g., Google Cloud Run, AWS App Runner, Fly.io) or an orchestrated cluster (e.g., Amazon ECS, Google Kubernetes Engine)?
2. **TLS & Routing Strategy**:
   - How will HTTPS certificates be provisioned and renewed?
   - Will a unified reverse proxy / CDN (e.g., Cloudflare, AWS CloudFront) route `/api/*` to the backend and all other routes to Next.js under a single domain?
3. **Database Topology**:
   - Which managed PostgreSQL service will be provisioned (e.g., Amazon RDS, Google Cloud SQL, Neon, Supabase)?
   - How will database schema migrations (`alembic upgrade head`) be executed during releases (e.g., pre-deploy job, init container)?
4. **Secrets & Config Delivery**:
   - What secrets manager will inject database credentials and future LLM API keys at runtime?
5. **Observability & Monitoring**:
   - Where will structured JSON application logs and container metrics be sent (e.g., Datadog, Prometheus/Grafana, CloudWatch)?
   - What alerting thresholds will be defined for HTTP 5xx errors and container restarts?
6. **Container Registry & Delivery Pipeline**:
   - Which private container registry will store production images (e.g., Amazon ECR, GitHub Packages, Google Artifact Registry)?
   - What branch or tag triggers deployment, and what rollback strategy is required?
