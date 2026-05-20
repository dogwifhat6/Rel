"""
Voice-to-SQL Query App — Prototype 2
-------------------------------------
3 tables in PostgreSQL:
  - cities          (bounding boxes for each city)
  - alerts          (alert metadata: type, severity, timestamp)
  - alert_readings  (coordinates + sensor values, linked to alerts)

The LLM generates SQL that can:
  - Query any of the 3 tables
  - JOIN alerts → alert_readings → cities (via lat/lon bounding-box match)
  - Answer questions like "where did the critical alert happen?"
"""


import os
import re
import tempfile
from typing import List, Tuple

from dotenv import load_dotenv
load_dotenv()
import pandas as pd
import streamlit as st
import psycopg2
import psycopg2.extras
import requests
import sounddevice as sd
from scipy.io.wavfile import write as wav_write

SAMPLE_RATE=16000
DEFAULT_DURATION=10
WHISPER_MODEL_SIZE="base"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5"

DB_CONFIG={
    "host":"localhost",
    "port":5432,
    "dbname":"city_alerte",
    "user":"postgres",
    "password":os.getenv("PASS"),
}

DISALLOWED_KEYWORDS = [
    "DELETE", "UPDATE", "INSERT", "DROP", "ALTER",
    "TRUNCATE", "CREATE", "GRANT", "REVOKE", "REPLACE",
    "MERGE", "EXEC", "EXECUTE", "CALL", "COPY",
]



SCHEMA_DESCRIPTION = """You have 3 related tables in a PostgreSQL database.

TABLE 1: cities  (15 rows — master list with bounding boxes)
  - city_id          INTEGER  PRIMARY KEY
  - city_name        VARCHAR  UNIQUE (e.g. 'Mumbai', 'Delhi', 'Jaipur')
  - state            VARCHAR  (e.g. 'Maharashtra', 'Karnataka')
  - boundary_lat_min NUMERIC  (south edge of city's bounding box)
  - boundary_lat_max NUMERIC  (north edge)
  - boundary_lon_min NUMERIC  (west edge)
  - boundary_lon_max NUMERIC  (east edge)

TABLE 2: alerts  (40 rows — alert metadata)
  - alert_id    INTEGER   PRIMARY KEY
  - alert_type  VARCHAR   ('HIGH_TEMP', 'EXTREME_HEAT', 'HIGH_HUMIDITY',
                          'LOW_HUMIDITY', 'EXTREME_BANDWIDTH', 'GENERAL')
  - severity    VARCHAR   ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')
  - detected_at TIMESTAMP (when alert fired)

TABLE 3: alert_readings  (40 rows — one per alert, contains location + sensor values)
  - reading_id  INTEGER  PRIMARY KEY
  - alert_id    INTEGER  FOREIGN KEY → alerts(alert_id)
  - latitude    NUMERIC
  - longitude   NUMERIC
  - temperature NUMERIC  (0 to 50, °C)
  - humidity    NUMERIC  (0 to 100, %)
  - bandwidth   NUMERIC  (-100 to 100)

RELATIONSHIPS:
  alerts (1) ──< alert_readings (1)   via alert_id
  alert_readings → cities             via SPATIAL JOIN on coordinates:
      r.latitude  BETWEEN c.boundary_lat_min AND c.boundary_lat_max
      AND r.longitude BETWEEN c.boundary_lon_min AND c.boundary_lon_max

IMPORTANT:
  - To find which city an alert came from, you MUST spatial-JOIN
    alert_readings → cities using the BETWEEN conditions above.
  - There is NO direct city_id column in alerts or alert_readings.
  - Use LEFT JOIN if a reading might fall outside all city boundaries.
  - Always use table aliases in JOINs (e.g. a.alert_id, r.latitude, c.city_name).
"""

def record_audio(duration:int,sample_rate:int)->str:
    """Records 'duration' seconds of mono audio from default mic.Returns thepath to the temporary .WAV file"""
    audio = sd.rec(int(duration*sample_rate),
                samplerate=sample_rate,
                channels=1,
                dtype="int16")
    sd.wait()
    tmp = tempfile.NamedTemporaryFile(delete=False,suffix=".wav")
    tmp.close()
    wav_write(tmp.name,sample_rate,audio)
    return tmp.name

@st.cache_resource(show_spinner=False)
def load_whisper_model(model_size:str):
    """Load the Whisper model once and cache it for the session"""
    from faster_whisper import WhisperModel
    return WhisperModel(model_size,device="cpu",compute_type="int8")

def transcribe_audio(wav_path:str)->str:
    """Run Whisper on a .wav file and return the transcribed string"""
    model = load_whisper_model(WHISPER_MODEL_SIZE)
    segments, _ = model.transcribe(wav_path,beam_size=5)
    return " ".join(seg.text for seg in segments).strip()

@st.cache_resource(show_spinner=False)
def get_db_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    return conn

SQL_GEN_PROMPT = """You are a PostgreSQL expert that converts natural-language questions into safe SELECT queries.

DATABASE SCHEMA:
{schema}

STRICT RULES:
1. Return ONLY a single SELECT statement. No explanation, no markdown, no code fences.
2. NEVER use INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, GRANT, REVOKE, or any statement that modifies data.
3. If the user asks to modify, delete, insert, or update data, return EXACTLY this literal text instead of SQL:
   ERROR: Only read queries are allowed.
4. Use ILIKE for case-insensitive city matching (e.g. city_name ILIKE 'Mumbai').
5. City names may contain typos or speech-recognition errors. Correct obvious mistakes silently
   (e.g. 'mumby' -> 'Mumbai', 'banglore' -> 'Bangalore').
6. The question may come from voice transcription with errors. Treat homophones charitably
   ('rose'/'road'/'rho' -> 'row', 'Bombay' -> 'Mumbai', spoken numbers -> digits).
7. You may use aggregates (COUNT, AVG, MIN, MAX, SUM), GROUP BY, ORDER BY, LIMIT, and WHERE filters.
8. Single statement only — no semicolons in the middle, only at the end.
9. Always alias aggregate columns (e.g. AVG(temperature) AS avg_temperature).
10. To find which city an alert came from, JOIN alert_readings -> cities using:
    r.latitude  BETWEEN c.boundary_lat_min AND c.boundary_lat_max
    AND r.longitude BETWEEN c.boundary_lon_min AND c.boundary_lon_max
11. Use table aliases: a for alerts, r for alert_readings, c for cities.
12. Only return the ERROR line if the user CLEARLY asks to modify data. Awkward wording is not a reason to refuse.

EXAMPLES:

Q: Show me all critical alerts
A: SELECT * FROM alerts WHERE severity = 'CRITICAL' ORDER BY detected_at DESC;

Q: Which city did the most recent critical alert come from?
A: SELECT c.city_name, c.state, a.alert_type, a.severity, a.detected_at, r.latitude, r.longitude
   FROM alerts a
   JOIN alert_readings r ON r.alert_id = a.alert_id
   JOIN cities c
     ON r.latitude  BETWEEN c.boundary_lat_min AND c.boundary_lat_max
    AND r.longitude BETWEEN c.boundary_lon_min AND c.boundary_lon_max
   WHERE a.severity = 'CRITICAL'
   ORDER BY a.detected_at DESC
   LIMIT 1;

Q: How many alerts per city?
A: SELECT c.city_name, COUNT(a.alert_id) AS alert_count
   FROM cities c
   LEFT JOIN alert_readings r
     ON r.latitude  BETWEEN c.boundary_lat_min AND c.boundary_lat_max
    AND r.longitude BETWEEN c.boundary_lon_min AND c.boundary_lon_max
   LEFT JOIN alerts a ON a.alert_id = r.alert_id
   GROUP BY c.city_name
   ORDER BY alert_count DESC;

Q: Show me alerts in Mumbai sorted by severity
A: SELECT a.alert_id, a.alert_type, a.severity, a.detected_at, r.temperature, r.humidity, r.bandwidth
   FROM alerts a
   JOIN alert_readings r ON r.alert_id = a.alert_id
   JOIN cities c
     ON r.latitude  BETWEEN c.boundary_lat_min AND c.boundary_lat_max
    AND r.longitude BETWEEN c.boundary_lon_min AND c.boundary_lon_max
   WHERE c.city_name ILIKE 'Mumbai'
   ORDER BY CASE a.severity
       WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'MEDIUM' THEN 3 WHEN 'LOW' THEN 4
   END;

Q: Average temperature of all high-temp alerts
A: SELECT AVG(r.temperature) AS avg_temperature
   FROM alerts a
   JOIN alert_readings r ON r.alert_id = a.alert_id
   WHERE a.alert_type = 'HIGH_TEMP';

Q: Delete all critical alerts
A: ERROR: Only read queries are allowed.

Now answer this question. Return ONLY the SQL (or the ERROR line):

Q: {question}
A:"""

def generate_sql(question:str)->str:
    """Single LLM call question -> SQL string (or 'ERROR:...')"""
    prompt = SQL_GEN_PROMPT.format(schema=SCHEMA_DESCRIPTION,question=question)
    payload = {
        "model":OLLAMA_MODEL,
        "prompt":prompt,
        "stream":False,
        "options":{"temperature": 0.0,
                   "top_p":0.1,
                   "stop":[";\n","Q:"]},
    }
    resp = requests.post(OLLAMA_URL,json=payload,timeout=120)
    resp.raise_for_status()
    raw = resp.json().get("response","").strip()
    return clean_sql_response(raw)

def clean_sql_response(raw:str)->str:
    """Strip code fences,leading 'A:' and trailing junk from the LLM output"""
    text = raw.strip()
    
    text = re.sub(r"^```(?:sql)?", "", text, flags=re.IGNORECASE).strip()
    
    text = re.sub(r"```$", "", text).strip()
    
    text = re.sub(r"^(A|Answer|SQL)\s*:\s*", "", text, flags=re.IGNORECASE).strip()
   
    if not text.upper().startswith("ERROR"):
        if ";" in text:
            text = text.split(";")[0].strip() + ";"
        elif text:
            text = text.rstrip(".") + ";"
    return text


def validate_sql(sql:str)->str:
    """Return (is_safe,error_message).Rejects everything which isnt a single SELECT statement"""
    s = sql.strip()

    if s.upper().startswith("ERROR"):
        return False,s
    
    if not s:
        return False,"Empty response from LLM"
    
    head = s.upper().lstrip("(")
    if not (head.startswith("SELECT") or head.startswith("WITH")):
        return False,"Only SELECT statements are allowed.!!"
    
    upper = s.upper()
    for kw in DISALLOWED_KEYWORDS:
        if re.search(rf"\b{kw}\b", upper):
            return False,f"Forbidden key word detected: {kw}"
        
    stripped = s.rstrip(";").rstrip()
    if ";" in stripped:
        return False,"Multiple SQL statements detected.Only one selected statement is allowed."
    
    return True,""
    
def run_sql(sql:str)->List[dict]:
    """Exceute the SQL and return the result as a list of dicts."""
    conn = get_db_connection()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]
    
def init_state():
    """Set default values for all session_state keys we'll read later"""
    defaults = {
        "transcript":"",
        "sql":"",
        "raw_llm":"",
        "rows":None,
        "status":"Idle",
        "error":"",
    }
    for k,v in defaults.items():
        st.session_state.setdefault(k,v)

def process_question(text:str):
    """Single class pipeline:question -> SQL ->safety check -> DB -> results or error message"""
    st.session_state.error = ""
    st.session_state.transcript = text
    st.session_state.sql = ""
    st.session_state.rows = None

    try:
        with st.spinner("Generating SQL..."):
            sql  =generate_sql(text)
        st.session_state.raw_llm = sql
    except requests.exceptions.ConnectionError:
        st.session_state.error = "Cannot reach Ollama"
        return
    except Exception as e:
        st.session_state.error = f"Error during SQL generation: {str(e)}"
        return 
    
    ok,err = validate_sql(sql)
    if not ok:
        st.session_state.sql = sql
        st.session_state.error = f"{err}"
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
    """Record audio, transcribe, then call process_question with the transcript."""
    st.session_state.error = ""

    # Record
    try:
        with st.spinner(f"🎙️ Recording for {duration}s..."):
            wav_path = record_audio(duration)
    except Exception as e:
        st.session_state.error = f"❌ Recording failed: {e}"
        return

    # Transcribe + process
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
        # Clean up the temp .wav file no matter what happened
        try:
            os.remove(wav_path)
        except OSError:
            pass
        
def main():
    st.set_page_config(page_title="Voice-to-SQL", page_icon="🔍", layout="wide")
    st.title("🔍 Voice-to-SQL Database Query")
    st.caption("3 connected tables: `cities` ↔ `alert_readings` ↔ `alerts`. Ask in natural language.")

    init_state()

    # ============ SIDEBAR ============
    with st.sidebar:
        st.header("🎙️ Input")
        duration = st.slider("Recording duration (seconds)", 5, 15, DEFAULT_DURATION)

        typed = st.text_area(
            "Type your question:",
            placeholder='e.g. "Which city did the most recent critical alert come from?"',
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
                "**Simple:**\n"
                "- *Show all critical alerts*\n"
                "- *How many alerts of each severity?*\n\n"
                "**With city lookup (spatial JOIN):**\n"
                "- *Which city did the most recent critical alert come from?*\n"
                "- *Show me alerts in Mumbai sorted by severity*\n"
                "- *How many alerts per city?*\n"
                "- *Average temperature of all HIGH_TEMP alerts*\n"
                "- *Cities with no alerts*\n\n"
                "**Blocked:**\n"
                "- ❌ *Delete all critical alerts*"
            )

    # ============ MAIN AREA ============
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()


    





