from __future__ import annotations

import json
from typing import Any, Optional

import requests

from vtsql.config import OLLAMA_URL
from vtsql.db_core import fetch_distinct_cities, run_select_query
from vtsql.filters_core import default_filter_state, merge_filter_delta, resolve_filter_state
from vtsql.llm import classify_intent, extract_filters_json
from vtsql.schemas import FilterState
from vtsql.sql_builder import build_sql_and_params, normalized_filter_debug


def _filter_state_to_dict(fs: FilterState | dict[str, Any] | None) -> dict[str, Any]:
    if fs is None:
        return default_filter_state()
    if isinstance(fs, FilterState):
        return fs.model_dump()
    return dict(fs)


def check_ollama() -> tuple[bool, str]:
    try:
        base = OLLAMA_URL.rsplit("/api/", 1)[0]
        r = requests.get(f"{base}/api/tags", timeout=5)
        if r.ok:
            return True, "ok"
        return False, f"status {r.status_code}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def check_postgres(db_overrides: dict[str, Any] | None = None) -> tuple[bool, str]:
    try:
        fetch_distinct_cities(db_overrides)
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def run_intent(text: str) -> dict[str, Any]:
    raw, parsed = classify_intent(text.strip())
    return {"intent": parsed.get("intent", "modify"), "reason": parsed.get("reason", ""), "raw": raw}


def run_extract_filters(
    text: str,
    previous_filters: FilterState | dict[str, Any] | None = None,
    db_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prev = _filter_state_to_dict(previous_filters)
    cities = fetch_distinct_cities(db_overrides)
    raw, parsed = extract_filters_json(text.strip(), cities, prev)
    resolved = merge_filter_delta(prev, parsed)
    return {"filters": FilterState(**resolved), "raw": raw}


def run_interpret(
    text: str,
    previous_filters: FilterState | dict[str, Any] | None = None,
    db_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise ValueError("text must not be empty")

    intent_data = run_intent(stripped)
    blocked = intent_data["intent"] == "modify"
    out: dict[str, Any] = {
        "transcript": stripped,
        "blocked": blocked,
        "intent": intent_data,
        "filters": None,
        "filters_raw": None,
        "message": None,
    }
    if blocked:
        out["message"] = intent_data.get("reason") or "Query classified as MODIFY and was blocked."
        return out

    extracted = run_extract_filters(stripped, previous_filters, db_overrides)
    out["filters"] = extracted["filters"]
    out["filters_raw"] = extracted["raw"]
    out["message"] = "filters_applied"
    return out


def run_query(
    filters: FilterState | dict[str, Any],
    db_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    f = filters if isinstance(filters, FilterState) else FilterState(**filters)
    sql, params = build_sql_and_params(
        f.cities,
        f.temperature_min,
        f.temperature_max,
        f.humidity_min,
        f.humidity_max,
        f.range_min,
        f.range_max,
    )
    rows, err = run_select_query(sql, params, db_overrides)
    if err:
        raise RuntimeError(err)
    norm = normalized_filter_debug(
        f.cities,
        f.temperature_min,
        f.temperature_max,
        f.humidity_min,
        f.humidity_max,
        f.range_min,
        f.range_max,
    )
    return {
        "sql": sql,
        "params": list(params),
        "row_count": len(rows),
        "rows": rows,
        "normalized_filters": norm,
    }


def run_nl_query(
    text: str,
    previous_filters: FilterState | dict[str, Any] | None = None,
    execute: bool = True,
    db_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    interpreted = run_interpret(text, previous_filters, db_overrides)
    result: dict[str, Any] = {
        "transcript": interpreted["transcript"],
        "blocked": interpreted["blocked"],
        "intent": interpreted["intent"],
        "filters": interpreted.get("filters"),
        "filters_raw": interpreted.get("filters_raw"),
        "sql": None,
        "params": None,
        "row_count": 0,
        "rows": [],
        "normalized_filters": None,
        "message": interpreted.get("message"),
    }
    if interpreted["blocked"] or not execute or interpreted.get("filters") is None:
        return result

    query_out = run_query(interpreted["filters"], db_overrides)
    result.update(
        {
            "sql": query_out["sql"],
            "params": query_out["params"],
            "row_count": query_out["row_count"],
            "rows": query_out["rows"],
            "normalized_filters": query_out["normalized_filters"],
        }
    )
    return result


def parsed_to_filter_state(parsed: dict[str, Any]) -> FilterState:
    return FilterState(**resolve_filter_state(parsed))
