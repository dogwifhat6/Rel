from __future__ import annotations

from typing import Any

import requests

from vtsql.config import OLLAMA_URL
from vtsql.db_core import run_select_query
from vtsql.llm import generate_sql, validate_sql


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
        # Just run a simple check query
        run_select_query("SELECT 1", db_overrides)
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def run_interpret(text: str) -> dict[str, Any]:
    from vtsql.prerequisites import check_prerequisites
    check_prerequisites()

    stripped = text.strip()
    if not stripped:
        raise ValueError("Text must not be empty")

    from vtsql.cache import check_cache
    sql = None
    from_cache = False
    try:
        sql = check_cache(stripped)
        if sql:
            from_cache = True
    except Exception:  # noqa: BLE001
        pass

    if not sql:
        try:
            sql = generate_sql(stripped)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Error during SQL generation: {exc}") from exc

    ok, err = validate_sql(sql)
    return {
        "transcript": stripped,
        "blocked": not ok,
        "sql": sql,
        "raw_llm": sql,
        "message": err if not ok else ("Semantic cache hit" if from_cache else "SQL generated successfully"),
        "from_cache": from_cache,
    }


def run_query(sql: str, db_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    from vtsql.prerequisites import check_prerequisites
    check_prerequisites()

    ok, err = validate_sql(sql)
    if not ok:
        raise ValueError(f"Safety Check Failed: {err}")

    rows, db_err = run_select_query(sql, db_overrides)
    if db_err:
        raise RuntimeError(db_err)

    return {
        "sql": sql,
        "row_count": len(rows),
        "rows": rows,
    }


def run_nl_query(
    text: str,
    execute: bool = True,
    db_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    interpreted = run_interpret(text)
    result = {
        "transcript": interpreted["transcript"],
        "blocked": interpreted["blocked"],
        "sql": interpreted["sql"],
        "raw_llm": interpreted["raw_llm"],
        "row_count": 0,
        "rows": [],
        "message": interpreted["message"],
    }

    if interpreted["blocked"] or not execute or not interpreted["sql"]:
        return result

    try:
        query_out = run_query(interpreted["sql"], db_overrides)
        result.update({
            "row_count": query_out["row_count"],
            "rows": query_out["rows"],
            "message": "Query executed successfully",
        })
        if not interpreted.get("from_cache"):
            from vtsql.cache import store_in_cache
            try:
                store_in_cache(interpreted["transcript"], interpreted["sql"])
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        result["message"] = f"Execution error: {exc}"

    return result
