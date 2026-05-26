from __future__ import annotations

import json

import streamlit as st

from vtsql.db import fetch_distinct_cities
from vtsql.filters import apply_extracted_filters_to_session, current_filter_state
from vtsql.llm import classify_intent, extract_filters_json


def reset_debug_state() -> None:
    for key in ("raw_intent_response", "raw_filter_response", "intent_parsed", "filter_parsed"):
        st.session_state.pop(key, None)


def process_user_text(query: str) -> None:
    reset_debug_state()
    stripped = query.strip()
    if not stripped:
        st.warning("Please provide text or record audio first.")
        return

    st.session_state["last_transcript"] = stripped

    try:
        intent_raw, intent_parsed = classify_intent(stripped)
        st.session_state["raw_intent_response"] = intent_raw
        st.session_state["intent_parsed"] = intent_parsed
    except RuntimeError as exc:
        st.error(str(exc))
        return
    except json.JSONDecodeError as exc:
        st.error(f"Intent model returned invalid JSON: {exc}")
        return

    if intent_parsed.get("intent") == "modify":
        st.error(f"This request is blocked ({intent_parsed.get('reason') or 'Query classified as MODIFY.'})")
        st.session_state["pipeline_note"] = "blocked_modify"
        return

    cities_cache = tuple(st.session_state.get("db_cities_cache") or fetch_distinct_cities())
    prev_filters = current_filter_state()
    try:
        filter_raw, filter_parsed = extract_filters_json(stripped, cities_cache, prev_filters)
        st.session_state["raw_filter_response"] = filter_raw
        st.session_state["filter_parsed"] = filter_parsed
    except RuntimeError as exc:
        st.error(str(exc))
        return
    except json.JSONDecodeError as exc:
        st.error(f"Filter model returned invalid JSON: {exc}")
        return

    apply_extracted_filters_to_session(filter_parsed, cities_cache)
    st.session_state["pipeline_note"] = "filters_applied"
