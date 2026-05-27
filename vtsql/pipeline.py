from __future__ import annotations

import requests
import streamlit as st

from vtsql.db import run_select_query
from vtsql.llm import generate_sql, validate_sql


def process_question(text: str) -> None:
    """Single pipeline step: question -> SQL -> safety check -> DB -> results or error message."""
    st.session_state["error"] = ""
    st.session_state["transcript"] = text
    st.session_state["sql"] = ""
    st.session_state["rows"] = None
    st.session_state["raw_llm"] = ""
    st.session_state["status"] = "Idle"

    from vtsql.cache import check_cache, store_in_cache

    sql = None
    from_cache = False
    try:
        with st.spinner("Checking semantic cache..."):
            sql = check_cache(text)
        if sql:
            from_cache = True
    except Exception:  # noqa: BLE001
        pass

    if not sql:
        try:
            with st.spinner("Generating SQL..."):
                sql = generate_sql(text)
            st.session_state["raw_llm"] = sql
        except requests.RequestException as exc:
            st.session_state["error"] = f"Cannot reach Ollama: {exc}"
            return
        except Exception as exc:  # noqa: BLE001
            st.session_state["error"] = f"Error during SQL generation: {exc}"
            return 

    ok, err = validate_sql(sql)
    if not ok:
        st.session_state["sql"] = sql
        st.session_state["error"] = f"Safety Block: {err}"
        return 

    st.session_state["sql"] = sql

    try:
        with st.spinner("💾 Running SQL on PostgreSQL..."):
            df, err = run_select_query(sql)
        if err:
            st.session_state["error"] = f"❌ Database error: {err}"
            return
        
        rows = df.to_dict(orient="records")
        st.session_state["rows"] = rows
        if from_cache:
            st.session_state["status"] = f"⚡ Semantic Cache hit! Query returned {len(rows)} row(s) (loaded from Cache)."
        else:
            st.session_state["status"] = f"✅ Query returned {len(rows)} row(s)."
            try:
                store_in_cache(text, sql)
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        st.session_state["error"] = f"❌ Database execution error: {exc}"


def process_user_text(text: str) -> None:
    """Backward compatibility wrapper for process_user_text."""
    process_question(text)
