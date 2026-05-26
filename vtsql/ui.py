from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from vtsql.audio import record_microphone, transcribe
from vtsql.config import COLUMN_RANGES, DEFAULT_DURATION, OLLAMA_MODEL, OLLAMA_URL, SAMPLE_RATE
from vtsql.db import fetch_distinct_cities, merged_db_config, run_select_query
from vtsql.filters import (
    apply_filter_state_snapshot,
    current_filter_state,
    ensure_city_options_initialized,
    ensure_slider_defaults_if_missing,
)
from vtsql.pipeline import process_user_text
from vtsql.sql_builder import build_sql_and_params, normalized_filter_debug


def _sync_query_params_from_state() -> None:
    state = current_filter_state()
    st.query_params["cities"] = ",".join(state["cities"])
    st.query_params["tmin"] = str(state["temperature_min"])
    st.query_params["tmax"] = str(state["temperature_max"])
    st.query_params["hmin"] = str(state["humidity_min"])
    st.query_params["hmax"] = str(state["humidity_max"])
    st.query_params["rmin"] = str(state["range_min"])
    st.query_params["rmax"] = str(state["range_max"])


def _load_query_params_into_state(db_cities: tuple[str, ...]) -> None:
    if st.session_state.get("_query_params_loaded"):
        return
    qp = st.query_params
    if not qp:
        st.session_state["_query_params_loaded"] = True
        return
    def _qp_text(key: str) -> str:
        value = qp.get(key, "")
        if isinstance(value, list):
            return value[0] if value else ""
        return str(value)

    snapshot = {
        "cities": [c.strip() for c in _qp_text("cities").split(",") if c.strip()],
        "temperature_min": _qp_text("tmin"),
        "temperature_max": _qp_text("tmax"),
        "humidity_min": _qp_text("hmin"),
        "humidity_max": _qp_text("hmax"),
        "range_min": _qp_text("rmin"),
        "range_max": _qp_text("rmax"),
    }
    apply_filter_state_snapshot(snapshot, db_cities)
    st.session_state["_query_params_loaded"] = True


def _record_history(nl_query: str, row_count: int, sql_text: str) -> None:
    history = list(st.session_state.get("query_history") or [])
    history.insert(
        0,
        {
            "ts": datetime.now().strftime("%H:%M:%S"),
            "query": nl_query or "(manual filter run)",
            "row_count": row_count,
            "sql": sql_text,
            "filters": current_filter_state(),
        },
    )
    st.session_state["query_history"] = history[:10]


def _human_filter_summary() -> dict[str, str]:
    s = current_filter_state()
    t_lo, t_hi = COLUMN_RANGES["temperature"]
    h_lo, h_hi = COLUMN_RANGES["humidity"]
    r_lo, r_hi = COLUMN_RANGES["range_metric"]
    cities = ", ".join(s["cities"]) if s["cities"] else "Any"
    temp = f"{s['temperature_min']}C - {s['temperature_max']}C" if (s["temperature_min"], s["temperature_max"]) != (t_lo, t_hi) else "Any"
    hum = f"{s['humidity_min']}% - {s['humidity_max']}%" if (s["humidity_min"], s["humidity_max"]) != (h_lo, h_hi) else "Any"
    rng = f"{s['range_min']} - {s['range_max']}" if (s["range_min"], s["range_max"]) != (r_lo, r_hi) else "Any"
    return {"cities": cities, "temp": temp, "hum": hum, "range": rng}


def _show_filter_feedback_panel() -> None:
    s = _human_filter_summary()
    st.subheader("Extracted / Active Filters")
    c1, c2, c3, c4 = st.columns(4)
    if c1.button(f"Cities: {s['cities']}", key="focus_cities", width="stretch"):
        st.session_state["focus_filter"] = "cities"
    if c2.button(f"Temperature: {s['temp']}", key="focus_temp", width="stretch"):
        st.session_state["focus_filter"] = "temperature"
    if c3.button(f"Humidity: {s['hum']}", key="focus_hum", width="stretch"):
        st.session_state["focus_filter"] = "humidity"
    if c4.button(f"Range: {s['range']}", key="focus_range", width="stretch"):
        st.session_state["focus_filter"] = "range"


def render_app() -> None:
    st.set_page_config(page_title="Voice-to-SQL (local)", layout="wide")
    st.title("Voice-to-SQL Query (local PostgreSQL)")
    st.caption("Whisper + Ollama locally. SQL is built only in Python; MODIFY intents are rejected.")

    ensure_slider_defaults_if_missing()
    cities_from_db = fetch_distinct_cities()
    if "db_cities_cache" not in st.session_state:
        st.session_state["db_cities_cache"] = list(cities_from_db)
    elif st.sidebar.button("Refresh cities from DB", help="Clears caches and reloads DISTINCT city"):
        fetch_distinct_cities.clear()
        st.session_state["db_cities_cache"] = list(fetch_distinct_cities())
        cities_from_db = tuple(st.session_state["db_cities_cache"])
    cities_from_db = tuple(st.session_state.get("db_cities_cache") or cities_from_db)
    ensure_city_options_initialized(cities_from_db)
    _load_query_params_into_state(cities_from_db)

    with st.sidebar:
        st.header("Input")
        duration = st.slider("Recording duration (s)", 1, 60, DEFAULT_DURATION)
        typed = st.text_area("Or type your question", placeholder="Example: Cities with humidity under 70", height=140)
        st.multiselect(
            "Cities quick pick",
            options=list(st.session_state.get("cities_options_list") or cities_from_db),
            key="cities_sel",
            help="This stays in sync with extracted city filters.",
        )

        st.text_input("Save current query as", key="save_query_name")
        if st.button("Star Save", width="stretch"):
            name = (st.session_state.get("save_query_name") or "").strip()
            if not name:
                st.warning("Enter a name first.")
            else:
                saved = dict(st.session_state.get("saved_queries") or {})
                saved[name] = {
                    "transcript": st.session_state.get("last_transcript", ""),
                    "filters": current_filter_state(),
                }
                st.session_state["saved_queries"] = saved
                st.success(f"Saved query '{name}'")
        saved_names = sorted((st.session_state.get("saved_queries") or {}).keys())
        selected_saved = st.selectbox("Load saved query", [""] + saved_names, index=0)
        if st.button("Load saved", width="stretch") and selected_saved:
            payload = st.session_state["saved_queries"][selected_saved]
            apply_filter_state_snapshot(payload["filters"], cities_from_db)
            st.session_state["last_transcript"] = payload.get("transcript", "")
            st.session_state["pipeline_note"] = "loaded_saved_query"
            _sync_query_params_from_state()
            st.rerun()

        if st.button("Clear session debug", key="clr_dbg"):
            st.session_state.clear()
            ensure_slider_defaults_if_missing()
            st.rerun()

        submitted = st.button("Submit typed query", width="stretch")
        recorded = st.button("Record microphone", width="stretch")

        with st.expander("Connection hints"):
            cfg = merged_db_config()
            st.code(
                f"PostgreSQL -> {cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['dbname']}\n"
                f"Ollama -> {OLLAMA_URL} model={OLLAMA_MODEL}",
                language="text",
            )
            if cfg.get("password") in {"", "YOUR_PASSWORD"}:
                st.info("Database password appears unset. Use env vars or .streamlit/secrets.toml.")

        if submitted:
            process_user_text(typed)

        if recorded:
            try:
                with st.spinner("Listening..."):
                    samples = record_microphone(float(duration), SAMPLE_RATE)
                with st.spinner("Transcribing..."):
                    text = transcribe(samples, SAMPLE_RATE)
                process_user_text(text)
                st.success(text or "(empty transcription)")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Recording failed: {exc}. Install PortAudio and retry.")

        with st.expander("Query history (last 10)", expanded=False):
            for idx, item in enumerate(st.session_state.get("query_history") or []):
                label = f"{item['ts']} | {item['row_count']} rows | {item['query'][:40]}"
                if st.button(label, key=f"hist_{idx}", width="stretch"):
                    apply_filter_state_snapshot(item["filters"], cities_from_db)
                    st.session_state["last_transcript"] = item["query"]
                    st.session_state["pipeline_note"] = "history_replay"
                    _sync_query_params_from_state()
                    st.rerun()

    if st.session_state.get("last_transcript"):
        st.info(str(st.session_state.get("pipeline_note", "Last transcript")).replace("_", " "))
        st.markdown(f"**Transcript**: {st.session_state['last_transcript']}")

    _show_filter_feedback_panel()

    t_lo, t_hi = COLUMN_RANGES["temperature"]
    h_lo, h_hi = COLUMN_RANGES["humidity"]
    r_lo, r_hi = COLUMN_RANGES["range_metric"]

    focus = st.session_state.get("focus_filter")
    with st.expander("Cities filter", expanded=focus == "cities"):
        st.multiselect(
            "Cities (leave empty for all cities)",
            options=list(st.session_state.get("cities_options_list") or cities_from_db),
            key="cities_sel",
        )

    with st.expander("Temperature filter", expanded=focus == "temperature"):
        c1, c2 = st.columns(2)
        with c1:
            temp_min = st.slider("Temperature min (C)", t_lo, t_hi, key="temp_min_slider")
        with c2:
            temp_max = st.slider("Temperature max (C)", t_lo, t_hi, key="temp_max_slider")

    with st.expander("Humidity filter", expanded=focus == "humidity"):
        c1, c2 = st.columns(2)
        with c1:
            hum_min = st.slider("Humidity min (%)", h_lo, h_hi, key="hum_min_slider")
        with c2:
            hum_max = st.slider("Humidity max (%)", h_lo, h_hi, key="hum_max_slider")

    with st.expander("Range filter", expanded=focus == "range"):
        c1, c2 = st.columns(2)
        with c1:
            range_min = st.slider("Range min", r_lo, r_hi, key="range_min_slider")
        with c2:
            range_max = st.slider("Range max", r_lo, r_hi, key="range_max_slider")

    if temp_max < temp_min:
        st.session_state["temp_max_slider"] = temp_min
        st.rerun()
    if hum_max < hum_min:
        st.session_state["hum_max_slider"] = hum_min
        st.rerun()
    if range_max < range_min:
        st.session_state["range_max_slider"] = range_min
        st.rerun()

    city_selection = list(st.session_state.get("cities_sel") or [])

    run_query = st.button("Run Query", type="primary", width="stretch")
    sql_text, sql_params = build_sql_and_params(
        list(city_selection), temp_min, temp_max, hum_min, hum_max, range_min, range_max
    )
    st.session_state["_last_sql"] = sql_text
    st.session_state["_last_sql_params"] = sql_params
    st.session_state["_norm_debug"] = normalized_filter_debug(
        list(city_selection), temp_min, temp_max, hum_min, hum_max, range_min, range_max
    )
    _sync_query_params_from_state()

    if run_query:
        df, err = run_select_query(sql_text, sql_params)
        if err:
            st.session_state["_last_query_error"] = err
            st.error(f"Query failed: {err}")
        else:
            st.session_state["_last_query_error"] = None
            st.success(f"{len(df)} row(s)")
            st.dataframe(df, use_container_width=True)
            st.session_state["_last_result_df"] = df
            _record_history(st.session_state.get("last_transcript", ""), len(df), sql_text)
            _sync_query_params_from_state()

    if isinstance(st.session_state.get("_last_result_df"), pd.DataFrame):
        df_latest = st.session_state["_last_result_df"]
        if not df_latest.empty and {"city", "temperature", "humidity"}.issubset(df_latest.columns):
            chart_df = (
                df_latest.groupby("city", as_index=False)[["temperature", "humidity"]]
                .mean()
                .set_index("city")
            )
            st.subheader("Average metrics by city")
            st.bar_chart(chart_df)

    with st.expander("Debug panel", expanded=False):
        tab1, tab2 = st.tabs(["Pipeline JSON", "SQL"])
        with tab1:
            if st.session_state.get("raw_intent_response"):
                st.code(st.session_state["raw_intent_response"], language="json")
            if st.session_state.get("intent_parsed") is not None:
                st.json(st.session_state["intent_parsed"])
            if st.session_state.get("raw_filter_response"):
                st.code(st.session_state["raw_filter_response"], language="json")
            if st.session_state.get("filter_parsed") is not None:
                st.json(st.session_state["filter_parsed"])
            st.json(st.session_state.get("_norm_debug") or {})
        with tab2:
            st.code(sql_text + "\n-- params:\n-- " + str(tuple(sql_params)), language="sql")
            if st.session_state.get("_last_query_error"):
                st.error(st.session_state["_last_query_error"])
