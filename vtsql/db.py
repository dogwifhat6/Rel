from __future__ import annotations

from typing import Any, Optional

import pandas as pd
import streamlit as st

from vtsql.db_core import db_connect as _db_connect
from vtsql.db_core import fetch_distinct_cities as _fetch_distinct_cities
from vtsql.db_core import get_db_config
from vtsql.db_core import run_select_query as _run_select_query_rows


def merged_db_config() -> dict[str, Any]:
    cfg = get_db_config()
    try:
        sec = getattr(st, "secrets", None)
        if sec and "postgres" in sec:
            for k in ("host", "port", "dbname", "user", "password"):
                if k in sec["postgres"] and sec["postgres"][k] not in (None, ""):
                    v = sec["postgres"][k]
                    cfg[k] = int(v) if k == "port" else v
        elif sec and "database" in sec:
            for k in ("host", "port", "dbname", "user", "password"):
                if k in sec["database"] and sec["database"][k] not in (None, ""):
                    v = sec["database"][k]
                    cfg[k] = int(v) if k == "port" else v
    except (RuntimeError, FileNotFoundError):
        pass
    return cfg


def db_connect():
    return _db_connect(merged_db_config())


@st.cache_data(ttl=30)
def fetch_distinct_cities() -> tuple[str, ...]:
    try:
        return _fetch_distinct_cities(merged_db_config())
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not load city list from database: {exc}")
        return tuple()


def run_select_query(sql: str, params: tuple[Any, ...]) -> tuple[pd.DataFrame, Optional[str]]:
    rows, err = _run_select_query_rows(sql, params, merged_db_config())
    if err:
        return pd.DataFrame(), err
    return pd.DataFrame(rows), None
