# Voice-to-SQL Query App

A fully-local Streamlit app that lets you query a PostgreSQL `city_metrics` table using plain English (spoken or typed). No SQL knowledge is required.

## How it works

```text
User input (voice or text)
        ↓
  [Whisper] — transcribe audio to text (voice path only)
        ↓
  [Tool 1] Qwen 2.5 — classify intent (SELECT vs. MODIFY)
        ↓ blocked if MODIFY
  [Tool 2] Qwen 2.5 — extract filters as structured JSON
        ↓
  Sliders auto-update to reflect what was understood
        ↓ (user can adjust, then click Run Query)
  Python builds a parameterized SELECT statement
        ↓
  PostgreSQL → results table
```

Two LLM calls act as discrete tools: one guards against unsafe operations, the other extracts query parameters. SQL is always built by Python. The model never writes SQL directly.

## Prerequisites

- Python 3.9+
- PostgreSQL
- Ollama + `qwen2.5`
- `faster-whisper`
- PortAudio (required by `sounddevice`)

## Install dependencies

```bash
pip install -r requirements.txt
```

## Install and start Ollama

```bash
# Install from https://ollama.com/download, then:
ollama pull qwen2.5
ollama serve
```

## Install PortAudio

```bash
# macOS
brew install portaudio

# Ubuntu / Debian
sudo apt-get install portaudio19-dev
```

## Database setup

Create a database (for example `sample_city`) and run:

```bash
psql -U postgres -d sample_city -f sql/schema.sql
```

Expected schema:

```sql
CREATE TABLE city_metrics (
    id          SERIAL PRIMARY KEY,
    city        TEXT    NOT NULL,
    temperature INTEGER NOT NULL,
    humidity    INTEGER NOT NULL,
    "range"     INTEGER NOT NULL
);
```

## Configuration

Tune constants at the top of `app.py`:

- `SAMPLE_RATE`
- `DEFAULT_DURATION`
- `WHISPER_MODEL_SIZE`
- `OLLAMA_MODEL`
- `OLLAMA_URL`
- `COLUMN_RANGES`

### PostgreSQL credentials

The app resolves DB config in this order:

1. Environment variables (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`)
2. Streamlit secrets (`.streamlit/secrets.toml`)
3. Defaults in `app.py`

Set secrets locally:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Then edit `.streamlit/secrets.toml` and set your password.

## Run the app

```bash
streamlit run app.py
```

Open `http://localhost:8501`.

## REST API (integration)

For embedding in other applications (React, mobile, microservices), run the FastAPI server:

```bash
python run_api.py
```

- Swagger UI: `http://localhost:8000/docs`
- Full API guide: [docs/API.md](docs/API.md)

One-shot NL query:

```bash
curl -X POST http://localhost:8000/v1/nl-query \
  -H "Content-Type: application/json" \
  -d '{"text":"Mumbai temperature above 30","execute":true}'
```

## Usage

### Voice input

1. Set recording duration in the sidebar.
2. Click **Record microphone**.
3. Whisper transcribes locally.

### Text input

1. Type a query in the sidebar.
2. Click **Submit typed query**.

### After input

- Intent is classified first.
- MODIFY requests are blocked before any query execution.
- SELECT requests go to filter extraction.
- Sliders and city selection auto-update from extracted filters.
- You can manually adjust values, then click **Run Query**.

## Example queries

- `Show me Mumbai with temperature above 30`
- `Find rows where humidity is between 60 and 90`
- `Cities with range less than 300 and temperature under 25`
- `Delhi and Pune with humidity above 50`

Blocked examples:

- `Delete all rows in Mumbai`
- `Drop the city_metrics table`
- `Update temperature to 35`

## Debug panel

The collapsed Debug panel shows:

- Raw JSON response from Ollama
- Parsed intent JSON
- Parsed filter JSON
- Normalized filter values used for SQL construction
- SQL template and parameter tuple

## Privacy

Everything runs locally:

- Audio is recorded and transcribed on your machine.
- LLM inference runs through local Ollama.
- No external API is required for normal runtime.

## Limitations

- Only `SELECT` operations are supported by design.
- The `city_metrics` schema is hardcoded for this version.
- Voice quality and whisper model choice affect transcription accuracy.
- Ambiguous language can be misparsed; sliders let you correct values before running query.
