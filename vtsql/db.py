from __future__ import annotations

from typing import Any, Optional

import pandas as pd
import streamlit as st

from vtsql.db_core import db_connect as _db_connect
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


def run_select_query(sql: str) -> tuple[pd.DataFrame, Optional[str]]:
    rows, err = _run_select_query_rows(sql, merged_db_config())
    if err:
        return pd.DataFrame(), err
    return pd.DataFrame(rows), None
