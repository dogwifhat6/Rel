from __future__ import annotations

from typing import Any, Optional

import pandas as pd
import psycopg2

from vtsql.config import DEFAULT_DB_CONFIG


def get_db_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = dict(DEFAULT_DB_CONFIG)
    if overrides:
        for key in ("host", "port", "dbname", "user", "password"):
            if key in overrides and overrides[key] not in (None, ""):
                cfg[key] = int(overrides[key]) if key == "port" else overrides[key]
    return cfg


def db_connect(overrides: dict[str, Any] | None = None):
    cfg = get_db_config(overrides)
    return psycopg2.connect(
        host=cfg["host"],
        port=cfg["port"],
        dbname=cfg["dbname"],
        user=cfg["user"],
        password=cfg["password"],
    )


def fetch_distinct_cities(overrides: dict[str, Any] | None = None) -> tuple[str, ...]:
    with db_connect(overrides) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT TRIM(city) AS city FROM city_metrics "
                "WHERE city IS NOT NULL AND TRIM(city) <> '' ORDER BY city"
            )
            rows = [r[0] for r in cur.fetchall() if r[0]]
    return tuple(rows)


def run_select_query(
    sql: str, params: tuple[Any, ...], overrides: dict[str, Any] | None = None
) -> tuple[list[dict[str, Any]], Optional[str]]:
    try:
        with db_connect(overrides) as conn:
            df = pd.read_sql_query(sql, conn, params=params)
        return df.to_dict(orient="records"), None
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)
