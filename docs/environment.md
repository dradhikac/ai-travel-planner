# Environment Configuration & Secret Management

This document outlines the environment variable baseline and secret-handling policies for the AI Travel Concierge project.

---

## Environment Variables Baseline

| Variable Name | Used By | Required? | Default Value | Example Value | Secret? |
| :--- | :--- | :---: | :--- | :--- | :---: |
| `APP_ENV` | Backend (`backend/app/core/config.py`) | No | `development` | `production` | No |
| `LOG_LEVEL` | Backend (`backend/app/core/config.py`) | No | `INFO` | `DEBUG` | No |
| `CORS_ORIGINS` | Backend (`backend/app/core/config.py`) | No | `http://localhost:3000,http://127.0.0.1:3000` | `https://app.travel.example` | No |
| `NEXT_PUBLIC_API_BASE_URL` | Frontend (`frontend/src/lib/config.ts`) | No | `http://localhost:8000` | `https://api.travel.example` | No |
| `POSTGRES_USER` | Local Database (`docker-compose.yml`) | No | `postgres` | `postgres` | No |
| `POSTGRES_PASSWORD` | Local Database (`docker-compose.yml`) | Yes | *None (Required)* | `change-me-local-only` | Yes (Dev) |
| `POSTGRES_DB` | Local Database (`docker-compose.yml`) | No | `ai_travel_concierge` | `ai_travel_concierge` | No |
| `POSTGRES_PORT` | Local Database (`docker-compose.yml`) | No | `5432` | `5433` | No |
| `DATABASE_URL` | Backend (`backend/app/core/config.py`) | No | *None (Optional)* | `postgresql+psycopg://postgres:change-me-local-only@localhost:5432/ai_travel_concierge` | Yes (Dev) |

### Notes on Variables
- **`APP_ENV`**: Constrained to `development`, `test`, or `production`. Controls API documentation visibility (`/docs` disabled in production).
- **`LOG_LEVEL`**: Standard library logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`).
- **`CORS_ORIGINS`**: Comma-separated list of allowed origins. Wildcard `*` is explicitly rejected for security.
- **`NEXT_PUBLIC_API_BASE_URL`**: HTTP/HTTPS base URL used by frontend client requests. Trailing slashes are stripped automatically.
- **`POSTGRES_USER`**: Username for PostgreSQL container initialization and authentication.
- **`POSTGRES_PASSWORD`**: Password for PostgreSQL container. Required via interpolation `${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}` to prevent hardcoded defaults.
- **`POSTGRES_DB`**: Default database name created on container startup.
- **`POSTGRES_PORT`**: Host port bound to container port 5432 on `127.0.0.1`. Defaults to 5432.
- **`DATABASE_URL`**: Optional connection URL for relational database persistence. Uses SQLAlchemy format (`postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME`). The application starts normally when unset.

---

## Secret-Handling Guidelines

### 1. Never Commit Secrets or Real `.env` Files
- All `.env`, `.env.*`, and `*.local` files are ignored by [.gitignore](../.gitignore).
- Only `.env.example` files containing non-sensitive placeholders are committed.
- Pre-commit verifications enforce that no private keys, tokens, or credentials are added to tracked files.

### 2. Setting Up Local Environment Files

To configure your local environment, copy the template files:

#### PowerShell (Windows 11)
```powershell
# Root / Database container configuration
Copy-Item .env.example .env

# Backend configuration
Copy-Item backend\.env.example backend\.env

# Frontend configuration
Copy-Item frontend\.env.example frontend\.env.local
```

#### Bash
```bash
# Root / Database container configuration
cp .env.example .env

# Backend configuration
cp backend/.env.example backend/.env

# Frontend configuration
cp frontend/.env.example frontend/.env.local
```

### 3. Client Bundle Exposure Rule (`NEXT_PUBLIC_*`)
- Any environment variable prefixed with `NEXT_PUBLIC_` is embedded directly into client-side JavaScript bundles during compilation.
- **CRITICAL**: Never store private API keys, database credentials, encryption secrets, or user tokens in `NEXT_PUBLIC_*` variables.

### 4. Incident Response & Credential Rotation
If any credential or secret is inadvertently committed or exposed:
1. **Revoke and Rotate Immediately**: Invalidate the compromised credential at the service provider immediately.
2. **Remove from Repository**: Remove the sensitive material from the branch and rewrite history if needed before publication.
3. **Audit Access Logs**: Check service logs for unauthorized access during the exposure window.
