from __future__ import annotations

import os

SAMPLE_RATE = 16000
DEFAULT_DURATION = 10
WHISPER_MODEL_SIZE = "base"

OLLAMA_MODEL = "qwen2.5"
OLLAMA_URL = os.environ.get("OLLAMA_GENERATE_URL", "http://localhost:11434/api/generate")
OLLAMA_TIMEOUT_SEC = int(os.environ.get("OLLAMA_TIMEOUT_SEC", "120"))

COLUMN_RANGES = {
    "temperature": (0, 50),
    "humidity": (0, 100),
    "range_metric": (0, 1000),
}

DEFAULT_DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "5432")),
    "dbname": os.environ.get("DB_NAME", os.environ.get("DBNAME", "sample_city")),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", os.environ.get("PGPASSWORD", "YOUR_PASSWORD")),
}
