"""
Voice-to-SQL Query App (Direct Text-to-SQL)
-------------------------------------------
Single LLM call that:
  - Validates intent (rejects non-SELECT requests in the prompt)
  - Generates the SQL directly from the user's question

Then a regex safety check rejects anything that looks like a write/DDL
before sending it to PostgreSQL.
"""

import os
import re
import tempfile
from typing import List, Optional, Tuple
from dotenv import load_dotenv
load_dotenv()

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

DB_CONFIG = {
    "host":     "localhost",
    "port":     5432,
    "dbname":   "sample_city",
    "user":     "postgres",
    "password": os.getenv("PASS"),   # ← CHANGE TO YOUR PASSWORD
}

TABLE_NAME = "city_metrics"

# Multi-table schema description given to the LLM.
SCHEMA_DESCRIPTION = """You have 3 related tables in a PostgreSQL database.

TABLE 1: cities  (master table — one row per city)
  - city_id     INTEGER  PRIMARY KEY
  - city_name   VARCHAR  UNIQUE (e.g. 'Mumbai', 'Delhi', 'Jaipur')
  - state       VARCHAR  (e.g. 'Maharashtra', 'Karnataka')
  - country     VARCHAR  (default 'India')
  - population  INTEGER

TABLE 2: city_metrics  (sensor readings — many rows per city)
  - id           INTEGER   PRIMARY KEY
  - city_id      INTEGER   FOREIGN KEY → cities(city_id)
  - city         VARCHAR   (denormalized city name, also present)
  - temperature  NUMERIC   (0 to 50, °C)
  - humidity     NUMERIC   (0 to 100, %)
  - range        INTEGER   (0 to 1000)
  - recorded_at  TIMESTAMP (when the reading was taken)

TABLE 3: city_alerts  (alerts derived from extreme readings)
  - alert_id    INTEGER   PRIMARY KEY
  - metric_id   INTEGER   FOREIGN KEY → city_metrics(id)
  - alert_type  VARCHAR   ('HIGH_TEMP', 'EXTREME_HEAT', 'HIGH_HUMIDITY',
                          'LOW_HUMIDITY', 'EXTREME_RANGE', 'GENERAL')
  - severity    VARCHAR   ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')
  - message     TEXT
  - created_at  TIMESTAMP

RELATIONSHIPS:
  cities (1) ──< city_metrics (many) ──< city_alerts (many)

  JOIN cities to metrics:  cities.city_id = city_metrics.city_id
  JOIN metrics to alerts:  city_metrics.id = city_alerts.metric_id

NOTES:
  - Some cities (e.g. Bhopal-like additions) may have NO metric rows.
  - Use LEFT JOIN when the user asks for cities that might have no data.
  - Use "range" with double quotes when in doubt — it's a reserved-ish word.
  - Always reference columns with table aliases in JOINs (e.g. c.city_name).
"""

# Anything matching these keywords (as whole words) in the generated SQL = reject.
DISALLOWED_KEYWORDS = [
    "DELETE", "UPDATE", "INSERT", "DROP", "ALTER",
    "TRUNCATE", "CREATE", "GRANT", "REVOKE", "REPLACE",
    "MERGE", "EXEC", "EXECUTE", "CALL", "COPY",
]


# ---------------------------------------------------------------------------
# Audio recording
# ---------------------------------------------------------------------------
def record_audio(duration: int, sample_rate: int = SAMPLE_RATE) -> str:
    audio = sd.rec(int(duration * sample_rate),
                   samplerate=sample_rate, channels=1, dtype="int16")
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
# Database
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_db_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    return conn


# ---------------------------------------------------------------------------
# Text → SQL  (single LLM call)
# ---------------------------------------------------------------------------
SQL_GEN_PROMPT = """You are a PostgreSQL expert that converts natural-language questions into safe SELECT queries.

DATABASE SCHEMA:
{schema}

STRICT RULES:
1. Return ONLY a single SELECT statement. No explanation, no markdown, no code fences.
2. NEVER use INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, GRANT, REVOKE, or any statement that modifies data.
3. If the user asks to modify, delete, insert, or update data, return EXACTLY this literal text instead of SQL:
   ERROR: Only read queries are allowed.
4. Use ILIKE for case-insensitive city matching (e.g. city ILIKE 'Mumbai').
5. City names may contain typos or speech-recognition errors. Correct obvious mistakes (e.g. 'mumby' -> 'Mumbai', 'ahmdbd' -> 'Ahmedabad') silently.
6. The question may come from voice transcription with errors. Treat homophones charitably:
   - "rose", "road", "rho", "row's" -> "row"
   - "Bombay" -> "Mumbai", "Madras" -> "Chennai", "Calcutta" -> "Kolkata", "Bangalor" -> "Bangalore"
   - Numbers spoken as words ("twenty" -> 20, "minus fifty" -> -50)
   Never refuse just because a word is unfamiliar — try to interpret the intent.
7. You may use aggregates (COUNT, AVG, MIN, MAX, SUM), GROUP BY, ORDER BY, LIMIT, and basic WHERE filters.
8. Single statement only — no semicolons in the middle, only at the end.
9. Always alias aggregate columns (e.g. AVG(temperature) AS avg_temperature).
10. Clamp filter values to the column ranges in the schema if the user gives out-of-range numbers.
11. Only return the ERROR line if the user clearly asks to MODIFY data (delete, insert, update, drop). Never use ERROR just because the wording is awkward.

EXAMPLES:

Q: Show me Mumbai with temperature above 30
A: SELECT * FROM city_metrics WHERE city ILIKE 'Mumbai' AND temperature > 30;

Q: Which row in Delhi has the least humidity?
A: SELECT * FROM city_metrics WHERE city ILIKE 'Delhi' ORDER BY humidity ASC LIMIT 1;

Q: Average temperature per city
A: SELECT city, AVG(temperature) AS avg_temperature FROM city_metrics GROUP BY city ORDER BY avg_temperature DESC;

Q: How many rows have range above 500?
A: SELECT COUNT(*) AS row_count FROM city_metrics WHERE "range" > 500;

Q: Show me all cities in Maharashtra with their average temperature
A: SELECT c.city_name, c.state, AVG(m.temperature) AS avg_temperature
   FROM cities c
   JOIN city_metrics m ON m.city_id = c.city_id
   WHERE c.state ILIKE 'Maharashtra'
   GROUP BY c.city_name, c.state
   ORDER BY avg_temperature DESC;

Q: Which cities have critical alerts?
A: SELECT DISTINCT c.city_name, a.severity, a.alert_type, a.message
   FROM city_alerts a
   JOIN city_metrics m ON m.id = a.metric_id
   JOIN cities c ON c.city_id = m.city_id
   WHERE a.severity = 'CRITICAL';

Q: List cities that have no metric data
A: SELECT c.city_name, c.state
   FROM cities c
   LEFT JOIN city_metrics m ON m.city_id = c.city_id
   WHERE m.id IS NULL;

Q: Total alerts per city sorted by count
A: SELECT c.city_name, COUNT(a.alert_id) AS alert_count
   FROM cities c
   LEFT JOIN city_metrics m ON m.city_id = c.city_id
   LEFT JOIN city_alerts a ON a.metric_id = m.id
   GROUP BY c.city_name
   ORDER BY alert_count DESC;

Q: Average humidity by state
A: SELECT c.state, AVG(m.humidity) AS avg_humidity
   FROM cities c
   JOIN city_metrics m ON m.city_id = c.city_id
   GROUP BY c.state
   ORDER BY avg_humidity DESC;

Q: Delete all Mumbai rows
A: ERROR: Only read queries are allowed.

Q: Give me rose with the highest humidity in Pune
A: SELECT * FROM city_metrics WHERE city ILIKE 'Pune' ORDER BY humidity DESC LIMIT 1;

Now answer this question. Return ONLY the SQL (or the ERROR line):

Q: {question}
A:"""


def generate_sql(question: str) -> str:
    """Single LLM call: question -> SQL string (or 'ERROR: ...')."""
    prompt = SQL_GEN_PROMPT.format(schema=SCHEMA_DESCRIPTION, question=question)
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0, "top_p": 0.1, "stop": [";\n", "Q:"]},
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
    resp.raise_for_status()
    raw = resp.json().get("response", "").strip()
    return clean_sql_response(raw)


def clean_sql_response(raw: str) -> str:
    """Strip code fences, leading 'A:' tags, etc."""
    text = raw.strip()
    # Remove ```sql / ``` fences
    text = re.sub(r"^```(?:sql)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()
    # Drop leading 'A:' or 'Answer:' the model sometimes adds
    text = re.sub(r"^(A|Answer|SQL)\s*:\s*", "", text, flags=re.IGNORECASE).strip()
    # Keep only up to the first complete statement (first semicolon)
    if not text.upper().startswith("ERROR"):
        if ";" in text:
            text = text.split(";")[0].strip() + ";"
        elif text:
            text = text.rstrip(".") + ";"
    return text


# ---------------------------------------------------------------------------
# Safety check on generated SQL
# ---------------------------------------------------------------------------
def validate_sql(sql: str) -> Tuple[bool, str]:
    """Return (is_safe, error_message). Reject anything that isn't a single SELECT."""
    s = sql.strip()

    if s.upper().startswith("ERROR"):
        return False, s

    if not s:
        return False, "Empty SQL returned by the model."

    # Must start with SELECT or WITH (CTE)
    head = s.upper().lstrip("(")
    if not (head.startswith("SELECT") or head.startswith("WITH")):
        return False, f"Only SELECT statements are allowed. Got: {s[:60]}..."

    # Block forbidden keywords as whole words
    upper = s.upper()
    for kw in DISALLOWED_KEYWORDS:
        if re.search(rf"\b{kw}\b", upper):
            return False, f"Forbidden keyword detected: {kw}"

    # Reject multiple statements (only one trailing semicolon allowed)
    stripped = s.rstrip(";").rstrip()
    if ";" in stripped:
        return False, "Multiple SQL statements are not allowed."

    return True, ""


# ---------------------------------------------------------------------------
# Run SQL
# ---------------------------------------------------------------------------
def run_sql(sql: str) -> List[dict]:
    conn = get_db_connection()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]



def init_state():
    defaults = {
        "transcript": "",
        "sql": "",
        "raw_llm": "",
        "rows": None,
        "status": "Idle. Ask a question by typing or speaking.",
        "error": "",
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)



def process_question(text: str):
    """Single-call pipeline: text → SQL → DB → results."""
    st.session_state.error = ""
    st.session_state.transcript = text
    st.session_state.sql = ""
    st.session_state.rows = None


    try:
        with st.spinner("🤖 Generating SQL with Qwen..."):
            sql = generate_sql(text)
        st.session_state.raw_llm = sql
    except requests.exceptions.ConnectionError:
        st.session_state.error = "❌ Cannot reach Ollama. Is it running?"
        return
    except Exception as e:
        st.session_state.error = f"❌ LLM call failed: {e}"
        return

  
    ok, err = validate_sql(sql)
    if not ok:
        st.session_state.sql = sql
        st.session_state.error = f"🚫 {err}"
        return

    st.session_state.sql = sql


    try:
        with st.spinner("💾 Running SQL on PostgreSQL..."):
            rows = run_sql(sql)
        st.session_state.rows = rows
        st.session_state.status = f"✅ Query returned {len(rows)} row(s)."
    except Exception as e:
        st.session_state.error = f"❌ Database error: {e}"


def handle_voice(duration: int):
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
        process_question(text)
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
    st.set_page_config(page_title="Voice-to-SQL", page_icon="🔍", layout="wide")
    st.title("🔍 Voice-to-SQL Database Query")
    st.caption("3 connected tables: `cities` → `city_metrics` → `city_alerts`. Ask questions in natural language.")

    init_state()

    # ============ SIDEBAR ============
    with st.sidebar:
        st.header("🎙️ Input")
        duration = st.slider("Recording duration (seconds)", 5, 15, DEFAULT_DURATION)

        typed = st.text_area(
            "Type your question:",
            placeholder='e.g. "Which row in Mumbai has the least temperature?"',
            height=120,
            key="typed_input",
        )

        col_v, col_t = st.columns(2)
        with col_v:
            if st.button("🎙️ Record", use_container_width=True):
                handle_voice(duration)
        with col_t:
            if st.button("✍️ Submit", use_container_width=True, type="primary"):
                if typed.strip():
                    process_question(typed.strip())
                else:
                    st.warning("Type something first.")

        st.divider()
        st.markdown(f"**Whisper:** `{WHISPER_MODEL_SIZE}`")
        st.markdown(f"**LLM:** `{OLLAMA_MODEL}`")

        with st.expander("💡 Example questions"):
            st.markdown(
                "**Single table:**\n"
                "- *Which row in Delhi is the coldest?*\n"
                "- *Average temperature per city*\n"
                "- *How many rows have humidity above 80?*\n\n"
                "**Multi-table (JOINs):**\n"
                "- *Show me all cities in Maharashtra*\n"
                "- *Which cities have critical alerts?*\n"
                "- *Average humidity by state*\n"
                "- *Total alerts per city*\n"
                "- *List cities that have no metric data*\n"
                "- *Show me alerts for Mumbai sorted by severity*\n\n"
                "**Blocked:**\n"
                "- ❌ *Delete all rows in Mumbai*"
            )

    if st.session_state.transcript:
        st.subheader("📝 Your Question")
        st.write(f"_{st.session_state.transcript}_")

    if st.session_state.error:
        st.error(st.session_state.error)

    if st.session_state.sql:
        st.subheader("🧾 Generated SQL")
        st.code(st.session_state.sql, language="sql")

    if st.session_state.rows is not None:
        rows = st.session_state.rows
        st.subheader(f"📋 Results ({len(rows)} rows)")
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        else:
            st.info("No rows matched.")

    if st.session_state.status and not st.session_state.error:
        st.info(st.session_state.status)

    # Debug
    if st.session_state.raw_llm:
        with st.expander("🐛 Debug: raw LLM output"):
            st.code(st.session_state.raw_llm, language="sql")


if __name__ == "__main__":
    main()