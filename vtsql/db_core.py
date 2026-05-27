from __future__ import annotations

from typing import Any, Optional

import psycopg2
import psycopg2.extras

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
    conn = psycopg2.connect(
        host=cfg["host"],
        port=cfg["port"],
        dbname=cfg["dbname"],
        user=cfg["user"],
        password=cfg["password"],
    )
    conn.autocommit = True
    return conn


def run_select_query(
    sql: str, overrides: dict[str, Any] | None = None
) -> tuple[list[dict[str, Any]], Optional[str]]:
    conn = None
    try:
        conn = db_connect(overrides)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            if cur.description:
                rows = [dict(r) for r in cur.fetchall()]
            else:
                rows = []
            return rows, None
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)
    finally:
        if conn is not None:
            conn.close()
