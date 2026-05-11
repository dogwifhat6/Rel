"""
Voice-to-SQL Query App
----------------------
A fully-local Streamlit app for querying a PostgreSQL `city_metrics` table
using voice or text. Architecture:

    User text/voice
        ↓ (Whisper if voice)
    TOOL 1 — Intent validation (Qwen 2.5)
        ✓ SELECT-like  → continue
        ✗ DELETE/UPDATE/INSERT/DROP → reject
        ↓
    TOOL 2 — Filter extraction as JSON (Qwen 2.5)
        ↓
    Sliders auto-update to show what was understood
        ↓ (user can tweak sliders, then click Run Query)
    Python builds parameterized SELECT SQL
        ↓
    PostgreSQL → results table
"""

import json
import os
import re
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import psycopg2
import psycopg2.extras
import requests
import sounddevice as sd
import streamlit as st
from scipy.io.wavfile import write as wav_write

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SAMPLE_RATE = 16000
DEFAULT_DURATION = 10
WHISPER_MODEL_SIZE = "base"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5"

# PostgreSQL connection — change to match your local setup
DB_CONFIG = {
    "host":     "localhost",
    "port":     5432,
    "dbname":   "sample_city",
    "user":     "postgres",
    "password": "mohan",   # ← CHANGE TO YOUR PASSWORD
}

TABLE_NAME = "city_metrics"

# Column ranges — used for slider bounds and validation
COLUMN_RANGES: Dict[str, Tuple[int, int]] = {
    "temperature": (0, 50),     # °C
    "humidity":    (0, 100),    # %
    "range":       (0, 1000),
}


# ---------------------------------------------------------------------------
# Audio recording
# ---------------------------------------------------------------------------
def record_audio(duration: int, sample_rate: int = SAMPLE_RATE) -> str:
    """Record mono 16 kHz audio from default mic, return temp .wav path."""
    audio = sd.rec(int(duration * sample_rate),
                   samplerate=sample_rate,
                   channels=1,
                   dtype="int16")
    sd.wait()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp.close()
    wav_write(tmp.name, sample_rate, audio)
    return tmp.name


# ---------------------------------------------------------------------------
# Whisper transcription
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def load_whisper_model(model_size: str = WHISPER_MODEL_SIZE):
    from faster_whisper import WhisperModel
    return WhisperModel(model_size, device="cpu", compute_type="int8")


def transcribe_audio(wav_path: str) -> str:
    model = load_whisper_model()
    segments, _ = model.transcribe(wav_path, beam_size=5)
    return " ".join(seg.text for seg in segments).strip()


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_db_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    return conn


# ---------------------------------------------------------------------------
# TOOL 1 — Intent validation
# ---------------------------------------------------------------------------
INTENT_PROMPT = """You are a strict intent classifier for a database query system.

The user wants to interact with a database. Decide if the request is a READ-ONLY operation (finding, filtering, selecting, showing, listing rows) or a MODIFY operation (inserting, updating, deleting, dropping, creating).

Return ONLY this JSON:
{{"intent": "select", "reason": ""}}
OR
{{"intent": "modify", "reason": "<short explanation>"}}

Rules:
- "select" for: find, show, list, get, filter, where, search, display, retrieve, query, fetch, look up
- "modify" for: delete, drop, remove, insert, add new row, update, change value, edit, modify, alter, create table
- If ambiguous but seems like a query, choose "select".

User sentence: {sentence}"""


def classify_intent(sentence: str) -> Tuple[str, str]:
    """Returns (intent, reason). intent is 'select' or 'modify'."""
    prompt = INTENT_PROMPT.format(sentence=sentence)
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0},
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
    resp.raise_for_status()
    raw = resp.json().get("response", "").strip()
    data = extract_json(raw) or {}
    intent = str(data.get("intent", "")).lower().strip()
    reason = str(data.get("reason", "")).strip()
    if intent not in ("select", "modify"):
        intent = "modify"  # fail-closed
        reason = reason or "Could not classify intent — blocking for safety."
    return intent, reason


# ---------------------------------------------------------------------------
# TOOL 2 — Filter extraction
# ---------------------------------------------------------------------------
FILTER_PROMPT = """Extract database filter parameters from the user's sentence and return JSON.

The database table has these columns:
- city: a city name (string). The user might say it with typos or speech recognition errors — correct obvious mistakes (e.g. "ahmdbd" -> "Ahmedabad", "mumby" -> "Mumbai") but do not invent a city if it sounds totally unfamiliar — pass it through as the user said it.
- temperature: integer or decimal between 0 and 50 (Celsius)
- humidity: integer or decimal between 0 and 100 (percent)
- range: integer between 0 and 1000

The user may phrase queries flexibly. Understand the intent.

Return ONLY this JSON shape:
{{
  "cities": [],
  "temperature_min": null,
  "temperature_max": null,
  "humidity_min": null,
  "humidity_max": null,
  "range_min": null,
  "range_max": null
}}

Rules:
- "cities" is a list of city names mentioned by the user (corrected for typos). Empty list = no city filter.
- Use null for any bound the user did not specify.
- "between X and Y" sets both min and max.
- "above X" / "more than X" / "greater than X" / "over X" sets the min only.
- "below X" / "less than X" / "under X" sets the max only.
- "exactly X" sets both min and max to X.
- Numbers must stay within their allowed range (temperature 0-50, humidity 0-100, range 0-1000). Clamp if needed.

User sentence: {sentence}"""


def extract_filters(sentence: str) -> Tuple[dict, str]:
    """Call LLM and return (parsed_dict, raw_text)."""
    prompt = FILTER_PROMPT.format(sentence=sentence)
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0, "top_p": 0.1},
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
    resp.raise_for_status()
    raw = resp.json().get("response", "").strip()
    return (extract_json(raw) or {}), raw


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------
def extract_json(raw: str) -> Optional[dict]:
    """Robust JSON extraction from LLM response."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    cleaned = re.sub(r"```(?:json)?", "", raw).strip("` \n")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def normalize_filters(payload: dict) -> dict:
    """
    Convert LLM output to a fully-populated filter dict with the slider bounds
    for any None values. Clamps everything to allowed ranges.
    """
    clean: Dict[str, Any] = {}

    cities = payload.get("cities") or []
    if not isinstance(cities, list):
        cities = []
    clean["cities"] = [str(c).strip() for c in cities
                       if isinstance(c, str) and str(c).strip()]

    for col, (lo, hi) in COLUMN_RANGES.items():
        raw_min = payload.get(f"{col}_min")
        raw_max = payload.get(f"{col}_max")

        def to_num(v, default):
            if v is None or v == "":
                return default
            try:
                return max(lo, min(hi, float(v)))
            except (TypeError, ValueError):
                return default

        clean[f"{col}_min"] = to_num(raw_min, lo)
        clean[f"{col}_max"] = to_num(raw_max, hi)

        if clean[f"{col}_min"] > clean[f"{col}_max"]:
            clean[f"{col}_min"], clean[f"{col}_max"] = (
                clean[f"{col}_max"], clean[f"{col}_min"])

    return clean


# ---------------------------------------------------------------------------
# SQL builder + executor
# ---------------------------------------------------------------------------
def build_and_run_sql(filters: dict) -> Tuple[List[dict], str]:
    """
    Build a parameterized SELECT from filters, run it, return (rows, display_sql).
    Only filters with non-default bounds add WHERE conditions.
    """
    where_parts: List[str] = []
    params: List[Any] = []

    cities = filters.get("cities") or []
    if cities:
        conds = " OR ".join(["city ILIKE %s"] * len(cities))
        where_parts.append(f"({conds})")
        params.extend(cities)

    for col, (lo, hi) in COLUMN_RANGES.items():
        cmin = filters.get(f"{col}_min", lo)
        cmax = filters.get(f"{col}_max", hi)
        if cmin > lo:
            where_parts.append(f"{col} >= %s")
            params.append(cmin)
        if cmax < hi:
            where_parts.append(f"{col} <= %s")
            params.append(cmax)

    where_clause = " AND ".join(where_parts) if where_parts else "TRUE"
    sql = (f"SELECT id, city, temperature, humidity, range "
           f"FROM {TABLE_NAME} WHERE {where_clause} ORDER BY city, id;")

    conn = get_db_connection()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]

    display_sql = sql
    for p in params:
        display_sql = display_sql.replace("%s", repr(p), 1)
    return rows, display_sql


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
def init_state():
    defaults = {
        "transcript": "",
        "intent": "",
        "intent_reason": "",
        "filters": {
            "cities": [],
            **{f"{c}_min": lo for c, (lo, hi) in COLUMN_RANGES.items()},
            **{f"{c}_max": hi for c, (lo, hi) in COLUMN_RANGES.items()},
        },
        "city_input": "",
        "sql": "",
        "rows": None,
        "status": "Idle. Speak, type, or use sliders to query.",
        "error": "",
        "raw_llm": "",
        "parsed_llm": None,
        "widget_version": 0,  # bumped each time filters auto-update, to force widget reset
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def process_nl_input(text: str):
    """Run intent validation + filter extraction. Updates session state."""
    st.session_state.error = ""
    st.session_state.transcript = text

    # TOOL 1 — Intent
    try:
        with st.spinner("🛡️ Validating intent..."):
            intent, reason = classify_intent(text)
    except requests.exceptions.ConnectionError:
        st.session_state.error = "❌ Cannot reach Ollama. Is it running?"
        return
    except Exception as e:
        st.session_state.error = f"❌ Intent check failed: {e}"
        return

    st.session_state.intent = intent
    st.session_state.intent_reason = reason

    if intent != "select":
        st.session_state.error = (
            f"🚫 Invalid request: only SELECT (read) queries are allowed. "
            f"Reason: {reason}"
        )
        return

    # TOOL 2 — Filters
    try:
        with st.spinner("🧩 Extracting filters with Qwen..."):
            parsed, raw_text = extract_filters(text)
    except Exception as e:
        st.session_state.error = f"❌ Filter extraction failed: {e}"
        return

    st.session_state.raw_llm = raw_text
    st.session_state.parsed_llm = parsed
    filters = normalize_filters(parsed)
    st.session_state.filters = filters
    st.session_state.city_input = ", ".join(filters["cities"])

    # Bump the widget version — this changes every widget key, forcing Streamlit
    # to create brand-new widgets initialized from the new filter values.
    st.session_state.widget_version += 1

    st.session_state.status = (
        "✅ Filters extracted. Adjust sliders if needed, then click Run Query."
    )
    st.rerun()


def run_query():
    """Read current slider state, build SQL, run on PostgreSQL."""
    st.session_state.error = ""
    try:
        with st.spinner("💾 Running SQL on PostgreSQL..."):
            rows, sql = build_and_run_sql(st.session_state.filters)
        st.session_state.rows = rows
        st.session_state.sql = sql
        st.session_state.status = f"✅ Query returned {len(rows)} row(s)."
    except Exception as e:
        st.session_state.error = f"❌ Database error: {e}"


def handle_voice(duration: int):
    """Record + transcribe, then run the NL pipeline."""
    st.session_state.error = ""
    try:
        with st.spinner(f"🎙️ Recording for {duration}s..."):
            wav_path = record_audio(duration)
    except Exception as e:
        st.session_state.error = f"❌ Recording failed: {e}"
        return

    try:
        with st.spinner("🧠 Transcribing with Whisper..."):
            text = transcribe_audio(wav_path)
        if not text:
            st.session_state.error = "⚠️ No speech detected."
            return
        process_nl_input(text)
    except Exception as e:
        st.session_state.error = f"❌ Transcription failed: {e}"
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="Voice-to-SQL Query", page_icon="🔍", layout="wide")
    st.title("🔍 Voice-to-SQL Database Query")
    st.caption(f"Table: `{TABLE_NAME}` — columns: city, temperature, humidity, range")

    init_state()

    # ============ SIDEBAR ============
    with st.sidebar:
        st.header("🎙️ Input")
        duration = st.slider("Recording duration (seconds)", 5, 15, DEFAULT_DURATION)

        typed = st.text_area(
            "Type your query:",
            placeholder='e.g. "Show me Mumbai and Delhi where temperature is between 25 and 40 and humidity above 70"',
            height=100,
            key="typed_input",
        )

        col_v, col_t = st.columns(2)
        with col_v:
            if st.button("🎙️ Record", use_container_width=True):
                handle_voice(duration)
        with col_t:
            if st.button("✍️ Submit", use_container_width=True, type="primary"):
                if typed.strip():
                    process_nl_input(typed.strip())
                else:
                    st.warning("Type something first.")

        st.divider()
        st.markdown(f"**Whisper:** `{WHISPER_MODEL_SIZE}`")
        st.markdown(f"**LLM:** `{OLLAMA_MODEL}`")

        with st.expander("💡 Example queries"):
            st.markdown(
                "- *Show me Mumbai with temperature above 30*\n"
                "- *Find rows where humidity is between 60 and 90*\n"
                "- *Cities with range less than 300 and temperature under 25*\n"
                "- *Delhi and Pune with humidity above 50*\n"
                "- ❌ *Delete all rows in Mumbai* — will be blocked"
            )

    # ============ MAIN AREA ============
    if st.session_state.transcript:
        st.subheader("📝 Last Input")
        st.write(f"_{st.session_state.transcript}_")

    if st.session_state.error:
        st.error(st.session_state.error)

    st.subheader("🎚️ Filter Controls")
    st.caption("These auto-update from voice/text input. You can also drag them manually.")

    f = st.session_state.filters

    v = st.session_state.widget_version  # version stamp for widget keys

    # City input — initialized from filters, then user can edit
    city_str = st.text_input(
        "City (comma-separated, leave empty for any):",
        value=st.session_state.city_input,
        key=f"city_input_widget_v{v}",
    )
    f["cities"] = [c.strip() for c in city_str.split(",") if c.strip()]

    # Range sliders — initial value comes from filters dict; user drags update widget state
    for col, (lo, hi) in COLUMN_RANGES.items():
        cur_min = int(f[f"{col}_min"])
        cur_max = int(f[f"{col}_max"])
        new_min, new_max = st.slider(
            f"{col.capitalize()} range",
            min_value=lo,
            max_value=hi,
            value=(cur_min, cur_max),
            step=1,
            key=f"slider_{col}_v{v}",
        )
        # Sync widget value back into filters dict so Run Query uses latest
        f[f"{col}_min"] = new_min
        f[f"{col}_max"] = new_max

    if st.button("▶️ Run Query", type="primary", use_container_width=True):
        run_query()

    if st.session_state.sql:
        st.subheader("🧾 Generated SQL")
        st.code(st.session_state.sql, language="sql")

    if st.session_state.rows is not None:
        rows = st.session_state.rows
        st.subheader(f"📋 Results ({len(rows)} rows)")
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        else:
            st.info("No rows matched the filter.")

    if st.session_state.status:
        st.info(st.session_state.status)

    # Debug panel — see exactly what the LLM returned
    if st.session_state.raw_llm or st.session_state.parsed_llm:
        with st.expander("🐛 Debug: LLM output"):
            st.markdown("**Raw response from Ollama:**")
            st.code(st.session_state.raw_llm or "(empty)", language="json")
            st.markdown("**Parsed dict:**")
            st.json(st.session_state.parsed_llm or {})
            st.markdown("**Normalized filters (used for sliders):**")
            st.json(st.session_state.filters)


if __name__ == "__main__":
    main()