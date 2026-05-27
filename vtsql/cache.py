from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Optional

import requests

from vtsql.config import CACHE_SIMILARITY_THRESHOLD, OLLAMA_EMBED_URL, OLLAMA_MODEL

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "query_cache.db")


def init_cache_db() -> None:
    """Create the caching table if it doesn't already exist."""
    conn = sqlite3.connect(DB_PATH)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS semantic_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT UNIQUE,
                    sql_query TEXT,
                    embedding TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
    finally:
        conn.close()


def get_embedding(text: str) -> Optional[list[float]]:
    """Fetch vector embedding for the input text using local Ollama model."""
    try:
        payload = {"model": OLLAMA_MODEL, "prompt": text.strip()}
        r = requests.post(OLLAMA_EMBED_URL, json=payload, timeout=30)
        r.raise_for_status()
        embedding = r.json().get("embedding")
        if isinstance(embedding, list) and all(isinstance(x, (int, float)) for x in embedding):
            return [float(x) for x in embedding]
        return None
    except Exception:  # noqa: BLE001
        return None


def dot_product(v1: list[float], v2: list[float]) -> float:
    return sum(x * y for x, y in zip(v1, v2))


def magnitude(v: list[float]) -> float:
    return sum(x * x for x in v) ** 0.5


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    mag1 = magnitude(v1)
    mag2 = magnitude(v2)
    if mag1 == 0 or mag2 == 0:
        return 0
    return dot_product(v1, v2) / (mag1 * mag2)


def check_cache(question: str) -> Optional[str]:
    """
    Checks the local semantic cache.
    Returns the cached SQL query if a match is found with similarity > CACHE_SIMILARITY_THRESHOLD.
    """
    # 1. First, check for an exact match (extremely fast)
    init_cache_db()
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("SELECT sql_query FROM semantic_cache WHERE question = ?", (question.strip(),))
        row = cur.fetchone()
        if row:
            return row[0]
    except Exception:  # noqa: BLE001
        pass
    finally:
        conn.close()

    # 2. If no exact match, fetch embedding of the new question and check similarity
    new_vector = get_embedding(question)
    if not new_vector:
        return None

    best_match_sql = None
    best_similarity = 0.0

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("SELECT sql_query, embedding FROM semantic_cache WHERE embedding IS NOT NULL")
        for sql_query, embed_str in cur.fetchall():
            try:
                cached_vector = json.loads(embed_str)
                if isinstance(cached_vector, list) and len(cached_vector) == len(new_vector):
                    sim = cosine_similarity(new_vector, cached_vector)
                    if sim > best_similarity:
                        best_similarity = sim
                        best_match_sql = sql_query
            except Exception:  # noqa: BLE001
                continue
    finally:
        conn.close()

    if best_similarity >= CACHE_SIMILARITY_THRESHOLD:
        return best_match_sql
    
    return None


def store_in_cache(question: str, sql_query: str) -> None:
    """Saves a question, its SQL translation, and its embedding vector to the semantic cache."""
    if sql_query.upper().startswith("ERROR"):
        # Do not cache safety block errors or bad queries
        return

    init_cache_db()
    embedding = get_embedding(question)
    embed_str = json.dumps(embedding) if embedding else None

    conn = sqlite3.connect(DB_PATH)
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO semantic_cache (question, sql_query, embedding) VALUES (?, ?, ?)",
                (question.strip(), sql_query, embed_str)
            )
    except Exception:  # noqa: BLE001
        pass
    finally:
        conn.close()
