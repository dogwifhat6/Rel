# Voice-to-SQL REST API

Run the API server:

```bash
pip install -r requirements.txt
ollama serve   # separate terminal
python run_api.py
```

- Base URL: `http://localhost:8000`
- OpenAPI docs: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Environment

Same variables as the Streamlit app:

| Variable | Purpose |
|---|---|
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | PostgreSQL |
| `OLLAMA_GENERATE_URL` | Ollama generate endpoint |
| `API_HOST`, `API_PORT` | API bind (default `0.0.0.0:8000`) |

Optional per-request DB override via JSON field `db` on pipeline endpoints.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health`, `/healthz` | Postgres + Ollama readiness |
| GET | `/v1/cities` | Distinct cities from DB |
| POST | `/v1/intent` | Classify SELECT vs MODIFY |
| POST | `/v1/extract-filters` | NL → structured filters (delta-aware) |
| POST | `/v1/interpret` | Intent + filters (no SQL execution) |
| POST | `/v1/query` | Execute parameterized SELECT from filters |
| POST | `/v1/nl-query` | Full pipeline: NL → filters → optional execute |
| POST | `/v1/transcribe` | Audio file → text (multipart) |
| POST | `/v1/voice-query` | Audio → NL pipeline (multipart) |

## Integration examples

### Full natural-language query

```bash
curl -s -X POST http://localhost:8000/v1/nl-query \
  -H "Content-Type: application/json" \
  -d '{"text":"Show Mumbai with temperature above 30","execute":true}'
```

### Conversational refinement (delta)

```bash
curl -s -X POST http://localhost:8000/v1/nl-query \
  -H "Content-Type: application/json" \
  -d '{
    "text": "now filter to only Delhi",
    "previous_filters": {
      "cities": ["Mumbai"],
      "temperature_min": 30,
      "temperature_max": 50,
      "humidity_min": 0,
      "humidity_max": 100,
      "range_min": 0,
      "range_max": 1000
    },
    "execute": true
  }'
```

### Step-by-step (for custom UIs)

1. `POST /v1/interpret` — get filters without hitting DB for rows
2. Let user edit filters in your app
3. `POST /v1/query` — run SQL with final filters

### Python client

```python
import requests

BASE = "http://localhost:8000"

def nl_query(text: str, previous_filters=None, execute=True):
    payload = {"text": text, "execute": execute}
    if previous_filters:
        payload["previous_filters"] = previous_filters
    r = requests.post(f"{BASE}/v1/nl-query", json=payload, timeout=180)
    r.raise_for_status()
    return r.json()

first = nl_query("Cities with humidity above 70")
second = nl_query("remove humidity filter", previous_filters=first["filters"])
print(second["row_count"], second["sql"])
```

### Voice upload

```bash
curl -s -X POST http://localhost:8000/v1/voice-query \
  -F "file=@sample.wav" \
  -F "language=en" \
  -F "execute=true"
```

## Response shape (`/v1/nl-query`)

```json
{
  "transcript": "Show Mumbai with temperature above 30",
  "blocked": false,
  "intent": {"intent": "select", "reason": "", "raw": "..."},
  "filters": {
    "cities": ["Mumbai"],
    "temperature_min": 30,
    "temperature_max": 50,
    "humidity_min": 0,
    "humidity_max": 100,
    "range_min": 0,
    "range_max": 1000
  },
  "sql": "SELECT ...",
  "params": ["Mumbai", 30, 50],
  "row_count": 1,
  "rows": [{"id": 1, "city": "Mumbai", ...}],
  "normalized_filters": {},
  "message": "filters_applied"
}
```

Blocked MODIFY requests return `blocked: true` and no SQL/rows.

## Architecture

```text
HTTP (FastAPI)
    → vtsql/services/pipeline_service.py
        → vtsql/llm.py (Ollama JSON tools)
        → vtsql/sql_builder.py (parameterized SELECT)
        → vtsql/db_core.py (PostgreSQL)
        → vtsql/audio_core.py (Whisper, voice endpoints)
```

Streamlit UI (`app.py`) and API share the same core modules.

## Python SDK wrapper

```python
from vtsql.client import VoiceToSQLClient

api = VoiceToSQLClient("http://localhost:8000")
result = api.nl_query("Mumbai temperature above 30")
follow_up = api.nl_query("now only Delhi", previous_filters=result["filters"])
```
