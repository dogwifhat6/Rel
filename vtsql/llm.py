from __future__ import annotations

import re
import requests

from vtsql.config import DISALLOWED_KEYWORDS, OLLAMA_MODEL, OLLAMA_TIMEOUT_SEC, OLLAMA_URL, SCHEMA_DESCRIPTION

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


def clean_sql_response(raw: str) -> str:
    """Strip code fences, leading 'A:' and trailing junk from the LLM output"""
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


def generate_sql(question: str) -> str:
    """Single LLM call question -> SQL string (or 'ERROR:...')"""
    prompt = SQL_GEN_PROMPT.format(schema=SCHEMA_DESCRIPTION, question=question)
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "top_p": 0.1,
            "stop": [";\n", "Q:"],
        },
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT_SEC)
    resp.raise_for_status()
    raw = resp.json().get("response", "").strip()
    return clean_sql_response(raw)


def validate_sql(sql: str) -> tuple[bool, str]:
    """Return (is_safe, error_message). Rejects everything which isn't a single SELECT/WITH statement."""
    s = sql.strip()

    if s.upper().startswith("ERROR"):
        return False, s
    
    if not s:
        return False, "Empty response from LLM"
    
    head = s.upper().lstrip("(")
    if not (head.startswith("SELECT") or head.startswith("WITH")):
        return False, "Only SELECT statements are allowed.!!"
    
    upper = s.upper()
    for kw in DISALLOWED_KEYWORDS:
        if re.search(rf"\b{kw}\b", upper):
            return False, f"Forbidden keyword detected: {kw}"
        
    stripped = s.rstrip(";").rstrip()
    if ";" in stripped:
        return False, "Multiple SQL statements detected. Only one statement is allowed."
    
    return True, ""
