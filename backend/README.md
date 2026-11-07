# UniBuddy Backend

FastAPI backend for UniBuddy. This is Milestone 1: app foundation + health
endpoint only. No database, auth, or AI integration yet — those come in
later milestones.

## Setup

From the `backend/` directory:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Copy the environment template and adjust if needed (defaults work for local dev):

```bash
cp .env.example .env
```

## Run

```bash
uvicorn app.main:app --reload
```

The API is now at `http://localhost:8000`. Interactive docs (Swagger UI):
`http://localhost:8000/docs`.

Check the health endpoint:

```bash
curl http://localhost:8000/api/v1/health
```

Expected response:

```json
{"status": "ok", "app": "UniBuddy Backend", "env": "development"}
```

## Test

```bash
pytest
```

Expected: 1 test passes (`test_health_check_returns_ok`).

## Project layout

```
backend/
  app/
    main.py      FastAPI app instance, CORS, routes
    config.py    Settings loaded from environment variables / .env
  tests/
    test_health.py
  requirements.txt
  .env.example
  pytest.ini
```
