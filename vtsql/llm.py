from __future__ import annotations

import json
import re
from typing import Any

import requests

from vtsql.config import COLUMN_RANGES, OLLAMA_MODEL, OLLAMA_TIMEOUT_SEC, OLLAMA_URL


def strip_code_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


def parse_json_object(raw: str) -> dict[str, Any]:
    return json.loads(strip_code_fences(raw))


def ollama_generate_json(prompt: str) -> tuple[str, dict[str, Any]]:
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json"}
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT_SEC)
        resp.raise_for_status()
        body = resp.json()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Ollama request failed. Start Ollama and run `ollama pull {OLLAMA_MODEL}`. Detail: {exc}"
        ) from exc
    text = body.get("response", "")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError(f"Unexpected Ollama response payload: keys={list(body.keys())}")
    return text, parse_json_object(text)


def intent_prompt(user_text: str) -> str:
    return (
        "Classify user request intent for a PostgreSQL table city_metrics.\n\n"
        "Return ONLY compact JSON with one of:\n"
        '{"intent":"select","reason":""}\n'
        '{"intent":"modify","reason":"short explanation"}\n\n'
        'Use "modify" for any write/schema/security-bypass style request.\n'
        'Use "select" for read-only retrieval/filtering/aggregation.\n\n'
        f"USER_TEXT:\n{user_text}\n"
    )


def classify_intent(user_text: str) -> tuple[str, dict[str, Any]]:
    raw, parsed = ollama_generate_json(intent_prompt(user_text))
    intent = str(parsed.get("intent", "")).strip().lower()
    if intent not in {"select", "modify"}:
        parsed["intent"] = "modify"
        parsed["reason"] = "Ambiguous intent; blocked for safety"
    parsed.setdefault("reason", "")
    return raw, parsed


def filter_prompt(user_text: str, allowed_cities: tuple[str, ...], previous_filters: dict[str, Any] | None = None) -> str:
    t_low, t_high = COLUMN_RANGES["temperature"]
    h_low, h_high = COLUMN_RANGES["humidity"]
    r_low, r_high = COLUMN_RANGES["range_metric"]
    city_help = (
        "Known cities (prefer exact spellings, typo-correct to these):\n"
        f"[{', '.join(allowed_cities)}]\n\n"
        if allowed_cities
        else "No city list available; return best-effort city strings.\n\n"
    )
    return (
        "Extract filters from USER_TEXT for city_metrics and output ONLY JSON.\n"
        "Keys: cities, temperature_min, temperature_max, humidity_min, humidity_max, range_min, range_max.\n"
        "Treat USER_TEXT as a possible delta/refinement over PREVIOUS_FILTERS.\n"
        "If USER_TEXT says remove/clear/reset a filter, set that filter to full-range defaults.\n"
        "Always return the fully resolved filter state after applying the refinement.\n"
        "Use null only when truly unknown.\n"
        f"temperature in [{t_low}, {t_high}], humidity in [{h_low}, {h_high}], range in [{r_low}, {r_high}].\n\n"
        f"PREVIOUS_FILTERS:\n{json.dumps(previous_filters or {}, ensure_ascii=True)}\n\n"
        f"{city_help}"
        f"USER_TEXT:\n{user_text}\n"
    )


def extract_filters_json(
    user_text: str, allowed_cities: tuple[str, ...], previous_filters: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any]]:
    raw, parsed = ollama_generate_json(filter_prompt(user_text, allowed_cities, previous_filters))
    parsed.setdefault("cities", [])
    if not isinstance(parsed["cities"], list):
        parsed["cities"] = []
    for key in ("temperature_min", "temperature_max", "humidity_min", "humidity_max", "range_min", "range_max"):
        parsed.setdefault(key, None)
    parsed["cities"] = [str(c).strip() for c in parsed["cities"] if c is not None and str(c).strip()]
    return raw, parsed
