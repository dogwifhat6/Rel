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


SQL_CRITIC_PROMPT = """You are a PostgreSQL Quality Assurance and Security Agent.
Your task is to analyze the generated SQL query for schema compliance, accuracy, and security.

DATABASE SCHEMA:
{schema}

USER QUESTION:
{question}

GENERATED SQL TO CRITIQUE:
{sql}

VALIDATION RULES:
1. Table & Column names must exactly match the schema.
2. Spatial joins between alert_readings and cities must use:
   r.latitude BETWEEN c.boundary_lat_min AND c.boundary_lat_max AND r.longitude BETWEEN c.boundary_lon_min AND c.boundary_lon_max
3. Ensure case-insensitive searches (ILIKE) are used for city name comparisons.
4. Ensure a.severity matches ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL') if severity filters are requested.
5. The query MUST be a SELECT or WITH query. If there are keywords like DELETE, UPDATE, INSERT, DROP, ALTER, TRUNCATE, reject it immediately.
6. Return EXACTLY the single word "APPROVED" if the query is safe, valid, and correct.
7. If there are syntax bugs, wrong columns, missing JOIN conditions, or safety violations, return "REJECTED: <detailed explanation of what is wrong and how to fix it>".

Now, evaluate the query. Return ONLY "APPROVED" or "REJECTED: <reasons>":
A:"""


SQL_REFINE_PROMPT = """You are a PostgreSQL expert correcting a previously failed or rejected SQL query.

DATABASE SCHEMA:
{schema}

USER QUESTION:
{question}

PREVIOUS SQL DRAFT:
{bad_sql}

CRITICISM/ERROR FEEDBACK:
{feedback}

STRICT RULES:
1. Correct the previous query to fix all issues mentioned in the criticism/feedback.
2. Follow all schema rules and safety restrictions.
3. Return ONLY a single SELECT/WITH statement. No markdown code blocks, no explanations.

Now return ONLY the corrected SQL:
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


def generate_sql_agentic(
    question: str,
    db_runner: callable | None = None
) -> tuple[str, list[dict[str, str]]]:
    """Orchestrates an agentic loop between Generator and Critic with auto-correction."""
    trace = []
    
    # 1. Generator generates first SQL draft
    sql = generate_sql(question)
    
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        step = {
            "attempt": str(attempt),
            "sql": sql,
            "critic": "UNKNOWN",
            "db": "UNKNOWN",
            "feedback": ""
        }
        
        # 1. Check static safety first
        is_safe, err_msg = validate_sql(sql)
        if not is_safe:
            step["critic"] = f"REJECTED (Static check): {err_msg}"
            step["feedback"] = f"Safety validator blocked this query. {err_msg}"
            trace.append(step)
            # If it's blocked, we must refine it or return error
            if "Only read queries are allowed" in err_msg or "Forbidden keyword" in err_msg:
                return sql, trace
        else:
            # 2. Invoke Critic Agent to critique the SQL
            critic_prompt = SQL_CRITIC_PROMPT.format(
                schema=SCHEMA_DESCRIPTION,
                question=question,
                sql=sql
            )
            payload = {
                "model": OLLAMA_MODEL,
                "prompt": critic_prompt,
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "top_p": 0.1
                }
            }
            try:
                resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT_SEC)
                resp.raise_for_status()
                critic_raw = resp.json().get("response", "").strip()
            except Exception as e:
                critic_raw = f"REJECTED: Critic service unreachable ({e})"

            step["critic"] = critic_raw
            
            if critic_raw.upper().startswith("APPROVED"):
                # Query approved by critic! Now attempt DB execution check if db_runner is available
                if db_runner:
                    _, db_err = db_runner(sql)
                    if db_err:
                        step["db"] = f"DATABASE ERROR: {db_err}"
                        step["feedback"] = f"PostgreSQL failed to execute this query: {db_err}"
                    else:
                        step["db"] = "SUCCESS"
                else:
                    step["db"] = "SKIPPED (no runner)"
            else:
                # Critic rejected the query
                feedback = critic_raw.split("REJECTED:", 1)[-1].strip() if "REJECTED:" in critic_raw.upper() else critic_raw
                step["feedback"] = f"Critic feedback: {feedback}"
                
            trace.append(step)
            
            # If approved by both Critic and DB, we are done!
            if step["critic"].upper().startswith("APPROVED") and (step["db"] in ("SUCCESS", "SKIPPED (no runner)")):
                return sql, trace

        # If we reached here, we have feedback and need to refine the query (unless it's the last attempt)
        if attempt < max_attempts:
            refine_prompt = SQL_REFINE_PROMPT.format(
                schema=SCHEMA_DESCRIPTION,
                question=question,
                bad_sql=sql,
                feedback=step["feedback"]
            )
            payload = {
                "model": OLLAMA_MODEL,
                "prompt": refine_prompt,
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "top_p": 0.1
                }
            }
            try:
                resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT_SEC)
                resp.raise_for_status()
                raw_refine = resp.json().get("response", "").strip()
                sql = clean_sql_response(raw_refine)
            except Exception as e:
                # Fallback to current SQL if LLM call fails
                break
                
    return sql, trace
