from __future__ import annotations

from typing import Any

import streamlit as st

from vtsql.config import COLUMN_RANGES
from vtsql.filters_core import clamp_int_optional, default_filter_state, resolve_filter_state


def ensure_slider_defaults_if_missing() -> None:
    defaults = default_filter_state()
    mapping = {
        "temp_min_slider": defaults["temperature_min"],
        "temp_max_slider": defaults["temperature_max"],
        "hum_min_slider": defaults["humidity_min"],
        "hum_max_slider": defaults["humidity_max"],
        "range_min_slider": defaults["range_min"],
        "range_max_slider": defaults["range_max"],
        "cities_sel": [],
    }
    for key, default in mapping.items():
        if key not in st.session_state:
            st.session_state[key] = default


def apply_extracted_filters_to_session(parsed: dict[str, Any], db_cities: tuple[str, ...]) -> None:
    resolved = resolve_filter_state(parsed)
    st.session_state["temp_min_slider"] = resolved["temperature_min"]
    st.session_state["temp_max_slider"] = resolved["temperature_max"]
    st.session_state["hum_min_slider"] = resolved["humidity_min"]
    st.session_state["hum_max_slider"] = resolved["humidity_max"]
    st.session_state["range_min_slider"] = resolved["range_min"]
    st.session_state["range_max_slider"] = resolved["range_max"]
    extracted = resolved["cities"]
    st.session_state["cities_options_list"] = sorted({*db_cities, *extracted}, key=lambda s: s.casefold())
    st.session_state["cities_sel"] = extracted


def ensure_city_options_initialized(db_cities: tuple[str, ...]) -> None:
    merged = sorted(set(db_cities) | set(st.session_state.get("cities_sel") or []), key=str.casefold)
    key = tuple(merged)
    if st.session_state.get("_cities_options_cache_key") != key:
        st.session_state["_cities_options_cache_key"] = key
        st.session_state["cities_options_list"] = merged


def current_filter_state() -> dict[str, Any]:
    defaults = default_filter_state()
    return {
        "cities": list(st.session_state.get("cities_sel") or []),
        "temperature_min": int(st.session_state.get("temp_min_slider", defaults["temperature_min"])),
        "temperature_max": int(st.session_state.get("temp_max_slider", defaults["temperature_max"])),
        "humidity_min": int(st.session_state.get("hum_min_slider", defaults["humidity_min"])),
        "humidity_max": int(st.session_state.get("hum_max_slider", defaults["humidity_max"])),
        "range_min": int(st.session_state.get("range_min_slider", defaults["range_min"])),
        "range_max": int(st.session_state.get("range_max_slider", defaults["range_max"])),
    }


def apply_filter_state_snapshot(snapshot: dict[str, Any], db_cities: tuple[str, ...]) -> None:
    parsed = {
        "cities": list(snapshot.get("cities") or []),
        "temperature_min": snapshot.get("temperature_min"),
        "temperature_max": snapshot.get("temperature_max"),
        "humidity_min": snapshot.get("humidity_min"),
        "humidity_max": snapshot.get("humidity_max"),
        "range_min": snapshot.get("range_min"),
        "range_max": snapshot.get("range_max"),
    }
    apply_extracted_filters_to_session(parsed, db_cities)
