# Module 0 — Project scaffold

**Status:** Done  
**What this module is:** the empty working skeleton of this app. It does **not** research companies, score leads, or write drafts yet. It proves the app can start, talk to Postgres, load provider config, and show a UI.

Read this first if you want to know what exists today and how the pieces connect.

---

## 1. What this project is

This repo (`c:\Excon`) is a **from-scratch** sales-intelligence app. Nothing in the running stack is imported from or linked to another codebase.

A seller describes their company, submits a target company, and the system will:

1. Research the target from public sources
2. Store claims with sources (never invent facts)
3. Score fit in Python and write a report with an LLM
4. Find decision-makers
5. Prepare outreach drafts for a human to review

The three spec files in this `docs/` folder are the product definition for later modules. Module 0 only built the runtime.

**Auth and workspaces are deferred.** Module 0 has no login.

---

## 2. What Module 0 actually did

Done:

- FastAPI backend with health endpoints
- PostgreSQL in Docker (created here; local credentials defined in this repo)
- SQLAlchemy engine/session + Alembic (ready for the first real tables)
- Vite + React + TypeScript frontend
- Docker Compose for `db` + `api` + `web`
- `.env` for MLX, Tavily, and Prospeo (gitignored)
- `.env.example` with variable names only
- Two pytest tests for health
- This document

Not done (later modules):

- Seller company / products / ICP
- Tavily, website reader, Prospeo, MLX clients
- Research orchestrator and evidence store
- Reports and scores
- Outreach drafts
- Login, users, workspaces

---

## 3. Database — where the details come from

Postgres is **not** a hosted/cloud database and was **not** copied from another project.

It is a Docker container defined in [docker-compose.yml](../docker-compose.yml) in this repo. Local development values:

| Setting | Value | Why |
|---|---|---|
| Engine | PostgreSQL 16 (official `postgres:16-alpine` image) | Spec III says PostgreSQL |
| Host | `localhost` from your machine; `db` inside Docker | Compose service name |
| Port | `5432` | Default Postgres port |
| User | `excon` | Local-only account for this repo |
| Password | `excon` | Local-only; not a production secret |
| Database name | `excon` | Matches this project |
| Data | Docker volume `excon_pgdata` | Survives container restarts |

The API uses `DATABASE_URL`. On the host that is `postgresql+psycopg://excon:excon@localhost:5432/excon`. Inside Compose it is overridden to `@db:5432` so the API container reaches the `db` container.

There are **no product tables yet**. Alembic runs on API start; with no revisions it only ensures the migration machinery works.

**Closing the terminal does not delete the database.** Data sits in a Docker volume on disk. Full explanation: [Module-0-database.md](Module-0-database.md).

---

## 4. How it works when you run it

```text
Browser  →  http://localhost:5173   (Vite React app)
                │
                │  fetch VITE_API_URL (http://localhost:8000)
                ▼
            FastAPI API  :8000
                │
                ├── /health            process is up
                ├── /health/ready      can talk to Postgres
                └── /health/providers  keys are present (booleans only)
                │
                ▼
            PostgreSQL  :5432  (Docker, database excon)
```

Three Docker services:

| Service | Image / build | Port | Job |
|---|---|---|---|
| `db` | `postgres:16-alpine` | 5432 | Database `excon` |
| `api` | `backend/Dockerfile` | 8000 | FastAPI + Alembic on start |
| `web` | `frontend/Dockerfile` | 5173 | Vite dev server |

On API start, `backend/docker-entrypoint.sh` runs `alembic upgrade head`, then Uvicorn.

Provider keys are **not used** in Module 0. They are only loaded from the environment. `/health/providers` returns whether each key/URL is set (`true`/`false`). It never returns the secret values.

The React page calls `/health` and `/health/providers` on load.

---

## 5. Repository layout

```text
c:\Excon\
  docs\
    Module-0.md                   this file
    (spec PDFs / txt)             product definition for later modules
  backend\
    app\
      main.py                     FastAPI app + CORS
      config.py                   Settings from .env
      api\routes\health.py        /health, /health/ready, /health/providers
      application\                empty — use cases go here
      domain\                     empty — business models go here
      infrastructure\
        database.py               SQLAlchemy engine, Session, Base
        models\                   empty — tables register here for Alembic
    alembic\                      migrations (no product tables yet)
    tests\test_health.py
    Dockerfile
    docker-entrypoint.sh
    requirements.txt
  frontend\
    src\App.tsx                   scaffold status screen
    src\main.tsx
    Dockerfile
  docker-compose.yml              db + api + web
  .env                            secrets — gitignored
  .env.example                    names only, safe to commit
  .gitignore
  README.md
```

Layers (only API + infrastructure exist today):

- **`api/`** — HTTP routes. No research logic, no provider SDKs.
- **`application/`** — use cases. Empty in Module 0.
- **`domain/`** — business rules. Must not import FastAPI, Tavily, Prospeo, or a specific database.
- **`infrastructure/`** — Postgres, and later Tavily / Prospeo / MLX adapters.

---

## 6. Configuration

Copy `.env.example` to `.env`. Never commit `.env`.

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL for the local `excon` database. |
| `MLX_BASE_URL` | OpenAI-compatible LLM server. |
| `MLX_MODEL` | Model id. |
| `TAVILY_API_KEY` | Web search (used from the tools module onward). |
| `PROSPEO_API_KEY` | People search (used later). |
| `CORS_ORIGINS` | Browser origins allowed to call the API (Vite on 5173). |
| `API_RELOAD` | When `true`, Uvicorn reloads on backend file changes. |

`app/config.py` reads `.env` from `backend/.env` or the repo-root `.env`. Docker Compose injects variables into the `api` container.

---

## 7. Backend internals

**App** (`backend/app/main.py`): builds FastAPI, enables CORS from `CORS_ORIGINS`, mounts the health router.

**Settings** (`backend/app/config.py`): Pydantic Settings. Cached via `get_settings()`.

**Database** (`backend/app/infrastructure/database.py`):

- `Base` — SQLAlchemy declarative base for future models
- `get_engine()` — one engine, `pool_pre_ping=True`
- `get_db()` — FastAPI dependency that yields a session and closes it

**Health routes** (`backend/app/api/routes/health.py`):

| Path | Meaning |
|---|---|
| `GET /health` | Process is running. No database. |
| `GET /health/ready` | `SELECT 1` against Postgres. `503` if the DB is down. |
| `GET /health/providers` | Booleans only: MLX URL set, Tavily key set, Prospeo key set. |

Interactive docs: http://localhost:8000/docs

**Tests** (`backend/tests/test_health.py`): live health returns `{"status":"ok"}`; providers endpoint returns booleans and does not leak key prefixes.

---

## 8. Frontend internals

Vite + React + TypeScript.

- `VITE_API_URL` defaults to `http://localhost:8000`.
- `App.tsx` fetches `/health` and `/health/providers` once on mount.
- No routing, no seller form, no login.

---

## 9. How to run

From the repo root:

```bash
docker compose up --build
```

- UI: http://localhost:5173
- API: http://localhost:8000/docs
- Postgres: `localhost:5432` (user / password / db: `excon`)

Backend tests:

```bash
cd backend
.\.venv\Scripts\Activate.ps1
pytest
```

Stop (keeps the data volume):

```bash
docker compose down
```

Wipe the local database volume and start empty:

```bash
docker compose down -v
docker compose up --build
```

---

## 10. What happens next

Build the working product without auth:

1. **Seller profile** — one local seller: company, products, ICP.
2. **Tools** — done; see [Module-2.md](Module-2.md).
3. **Research** — gap-driven loop, evidence store, honest gaps.
4. **Reports** — Python scores + LLM narrative with evidence links.
5. **Drafts** — decision-makers and channel drafts; review/edit/approve, no send.
6. **UI** — screens for that full flow.

Authentication / workspaces stay last.
