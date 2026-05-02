# BagsVault — Backend

FastAPI service backing the BagsVault dApp. Persists application state in MongoDB; exposes a JSON API under `/api`.

## Stack

- **FastAPI 0.110** (ASGI)
- **Motor 3.3** (async MongoDB driver)
- **Pydantic v2** (settings + models)
- **Uvicorn** (dev/prod server)

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then edit values
uvicorn app.main:app --reload # http://localhost:8000
```

Interactive API docs: http://localhost:8000/docs (Swagger) or http://localhost:8000/redoc.

## Layout

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI app, CORS, router registration
│   ├── config.py          # Pydantic settings (loads .env)
│   ├── database.py        # Motor client + db handle
│   ├── models/
│   │   ├── __init__.py
│   │   └── status.py      # StatusCheck Pydantic models
│   └── routers/
│       ├── __init__.py
│       └── status.py      # GET/POST /api/status
├── requirements.txt
├── pyproject.toml         # black, isort, mypy, pytest config
├── .env.example
└── README.md
```

## Environment

Copy `.env.example` to `.env`:

| Variable | Default | Description |
|---|---|---|
| `MONGO_URL` | `mongodb://localhost:27017` | Mongo connection string |
| `DB_NAME` | `bagsvault` | Database name |
| `CORS_ORIGINS` | `*` | Comma-separated origin allowlist |

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/` | Health probe — returns `{ "message": "Hello World" }` |
| `POST` | `/api/status` | Create a new StatusCheck |
| `GET` | `/api/status` | List recent StatusCheck records (max 1000) |

## Development

```bash
black .            # format
isort .            # sort imports
flake8 .           # lint
mypy app           # type-check
pytest             # run tests
```

All tooling is configured in `pyproject.toml` — no separate config files required.

## Production

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Or via Docker (see root `docker-compose.yml`).
