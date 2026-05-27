from __future__ import annotations

import os

SAMPLE_RATE = 16000
DEFAULT_DURATION = 10
WHISPER_MODEL_SIZE = "base"

OLLAMA_MODEL = "llama3.2:3b"
OLLAMA_URL = os.environ.get("OLLAMA_GENERATE_URL", "http://localhost:11434/api/generate")
OLLAMA_TIMEOUT_SEC = int(os.environ.get("OLLAMA_TIMEOUT_SEC", "120"))
OLLAMA_EMBED_URL = os.environ.get("OLLAMA_EMBED_URL", "http://localhost:11434/api/embeddings")
CACHE_SIMILARITY_THRESHOLD = 0.90

DEFAULT_DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "5432")),
    "dbname": os.environ.get("DB_NAME", os.environ.get("DBNAME", "city_alerte")),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", os.environ.get("PGPASSWORD", os.environ.get("PASS", ""))),
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
