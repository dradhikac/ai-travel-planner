# Local Development Guide

This guide provides instructions for setting up and running local development services for AI Travel Concierge.

---

## 1. Prerequisites

- **Windows 11**: [Docker Desktop](https://www.docker.com/products/docker-desktop/) must be installed and actively running. Ensure the Docker daemon has finished initializing before executing compose commands.
- **macOS / Linux**: Docker Engine with Docker Compose v2.

---

## 2. Environment Configuration

To configure environment variables for the database container, create a local `.env` file from the template at the project root:

### PowerShell (Windows 11)
```powershell
Copy-Item .env.example .env
```

### Bash
```bash
cp .env.example .env
```

> [!NOTE]
> The root `.env` file is strictly ignored by Git and should never be committed. The default values in `.env.example` are intended for local development only.

---

## 3. Database Service Management

The database service is defined in `docker-compose.yml` under the service name `db`. It uses `postgres:16-alpine` and publishes port `5432` bound strictly to `127.0.0.1` on the host machine.

### Start the Database Container
Start the PostgreSQL container in detached mode:
```powershell
docker compose up -d db
```

### Check Container Status
Verify container execution and health status:
```powershell
docker compose ps
```
The status will display `healthy` once the `pg_isready` probe confirms the PostgreSQL server is ready to accept connections.

### Inspect Service Logs
Follow or review database logs:
```powershell
# View recent logs
docker compose logs db

# Stream logs continuously
docker compose logs -f db
```

### Probe Database Readiness
Execute `pg_isready` directly within the container:
```powershell
docker compose exec db pg_isready
```

### Stop the Database Container
Stop and remove the container while preserving database data:
```powershell
docker compose down
```

> [!CAUTION]
> **Data Loss Warning**: Running `docker compose down -v` removes the named volume `postgres_data` (`ai_travel_concierge_postgres_data`) and **permanently deletes all stored database data**. Only use the `-v` flag if you explicitly intend to wipe the database and start fresh.

---

## 4. Port Conflicts & Customization

If host port `5432` is already in use by another local PostgreSQL installation or service, update `POSTGRES_PORT` in your local `.env` file:
```env
POSTGRES_PORT=5433
```
After modifying `.env`, run `docker compose up -d db` to bind to the new host port.
