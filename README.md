# Excon

Evidence-driven B2B sales intelligence, built from scratch in this repo. Seller setup, research, reports, and outreach drafts. Authentication and workspaces come later.

What exists today: [docs/Module-0.md](docs/Module-0.md) (scaffold), [docs/Module-2.md](docs/Module-2.md) (tools), [docs/Module-3.md](docs/Module-3.md) (research), [docs/Module-4.md](docs/Module-4.md) (seller profile), [docs/Module-5.md](docs/Module-5.md) (report), [docs/Module-6.md](docs/Module-6.md) (outreach drafts). Database persistence: [docs/Module-0-database.md](docs/Module-0-database.md). End-to-end walkthrough: [docs/Workflow.md](docs/Workflow.md).

Product specs in `docs/`: I (workflow + LLD), II (module blueprint), III (MVP stack).

## Stack

- Backend: Python, FastAPI, Pydantic, LangChain, LangGraph, SQLAlchemy, Alembic
- Database: PostgreSQL
- Frontend: React + TypeScript (Vite)
- Providers: MLX (Qwen), Tavily, Prospeo — configured in `.env`

## Setup

```bash
cp .env.example .env
# Fill MLX_BASE_URL, MLX_MODEL, TAVILY_API_KEY, PROSPEO_API_KEY
```

Never commit `.env`.

### Docker (API + Postgres + web)

```bash
docker compose up --build
```

- Web: http://localhost:5173
- API: http://localhost:8000/docs
- Postgres: `localhost:5432` (user / password / db: `excon`)

### Backend tests

```bash
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
```
