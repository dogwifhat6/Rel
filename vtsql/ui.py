from __future__ import annotations

import pandas as pd
import pydeck as pdk
import streamlit as st

from vtsql.audio import record_microphone, transcribe
from vtsql.config import DEFAULT_DURATION, OLLAMA_MODEL, SAMPLE_RATE, WHISPER_MODEL_SIZE
from vtsql.db import run_select_query
from vtsql.pipeline import process_question


def init_state() -> None:
    """Set default values for all session_state keys we'll read later."""
    defaults = {
        "transcript": "",
        "sql": "",
        "raw_llm": "",
        "rows": None,
        "status": "Idle",
        "error": "",
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


def handle_voice(duration: int) -> None:
    """Record audio, transcribe, then call process_question with the transcript."""
    st.session_state["error"] = ""

    # Record
    try:
        with st.spinner(f"🎙️ Recording for {duration}s..."):
            samples = record_microphone(float(duration), SAMPLE_RATE)
    except Exception as exc:  # noqa: BLE001
        st.session_state["error"] = f"❌ Recording failed: {exc}. Please install PortAudio and verify microphone access."
        return

    # Transcribe + process
    try:
        with st.spinner("🧠 Transcribing with Whisper..."):
            text = transcribe(samples, SAMPLE_RATE)
        if not text:
            st.session_state["error"] = "⚠️ No speech detected."
            return
        process_question(text)
    except Exception as exc:  # noqa: BLE001
        st.session_state["error"] = f"❌ Transcription failed: {exc}"


def render_geospatial_map(df: pd.DataFrame) -> None:
    """Renders city bounding box polygons and alert reading scatter points if coordinates are present."""
    if "latitude" not in df.columns or "longitude" not in df.columns:
        return

    # Clean up and filter rows with valid coordinates
    map_df = df.dropna(subset=["latitude", "longitude"]).copy()
    if map_df.empty:
        return

    # Convert lat/lon columns to floats
    map_df["latitude"] = map_df["latitude"].astype(float)
    map_df["longitude"] = map_df["longitude"].astype(float)

    # Determine point colors based on severity
    def get_color(row: pd.Series) -> list[int]:
        sev = str(row.get("severity") or "").upper()
        if "CRITICAL" in sev:
            return [220, 53, 69, 200]  # Red
        if "HIGH" in sev:
            return [253, 126, 20, 200]  # Orange
        if "MEDIUM" in sev:
            return [255, 193, 7, 200]  # Yellow
        if "LOW" in sev:
            return [40, 167, 69, 200]  # Green
        return [0, 123, 255, 200]  # Blue

    map_df["color"] = map_df.apply(get_color, axis=1)

    # Load all city boundaries from the database to display as background boundaries
    cities_polygons = []
    try:
        cities_df, err = run_select_query("SELECT city_name, boundary_lat_min, boundary_lat_max, boundary_lon_min, boundary_lon_max FROM cities")
        if not err and not cities_df.empty:
            for _, row in cities_df.iterrows():
                lat_min = float(row["boundary_lat_min"])
                lat_max = float(row["boundary_lat_max"])
                lon_min = float(row["boundary_lon_min"])
                lon_max = float(row["boundary_lon_max"])
                cities_polygons.append({
                    "name": row["city_name"],
                    "coordinates": [
                        [lon_min, lat_min],
                        [lon_max, lat_min],
                        [lon_max, lat_max],
                        [lon_min, lat_max],
                        [lon_min, lat_min]
                    ]
                })
    except Exception:  # noqa: BLE001
        pass

    layers = []

    # 1. Add background city polygons if available
    if cities_polygons:
        cities_poly_df = pd.DataFrame(cities_polygons)
        cities_layer = pdk.Layer(
            "PolygonLayer",
            cities_poly_df,
            get_polygon="coordinates",
            get_fill_color="[100, 149, 237, 30]",  # Translucent Cornflower Blue
            get_line_color="[100, 149, 237, 120]",
            line_width_min_pixels=1.5,
            pickable=True,
            auto_highlight=True,
        )
        layers.append(cities_layer)

    # 2. Add scatterplot layer for alert readings
    points_layer = pdk.Layer(
        "ScatterplotLayer",
        map_df,
        get_position="[longitude, latitude]",
        get_color="color",
        get_radius=12000,  # 12km radius
        radius_min_pixels=6,
        radius_max_pixels=25,
        pickable=True,
        auto_highlight=True,
    )
    layers.append(points_layer)

    # Center map on the mean coordinates of results
    mean_lat = float(map_df["latitude"].mean())
    mean_lon = float(map_df["longitude"].mean())

    view_state = pdk.ViewState(
        latitude=mean_lat,
        longitude=mean_lon,
        zoom=5.5,
        pitch=0,
    )

    st.subheader("🗺️ Spatial Alert Map")
    st.pydeck_chart(pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        tooltip={"text": "Coordinates: {latitude}, {longitude}\nDetails: {alert_type} ({severity})\nTemp: {temperature}°C | Humidity: {humidity}%"},
    ))


def render_app() -> None:
    st.set_page_config(page_title="Voice-to-SQL", page_icon="🔍", layout="wide")
    st.title("🔍 Voice-to-SQL Database Query")
    st.caption("3 connected tables: `cities` ↔ `alert_readings` ↔ `alerts`. Ask in natural language.")

    init_state()

    # ============ SIDEBAR ============
    with st.sidebar:
        st.header("🎙️ Input")
        duration = st.slider("Recording duration (seconds)", 5, 15, DEFAULT_DURATION)

        typed = st.text_area(
            "Type your question:",
            placeholder='e.g. "Which city did the most recent critical alert come from?"',
            height=120,
            key="typed_input",
        )

        col_v, col_t = st.columns(2)
        with col_v:
            if st.button("🎙️ Record", use_container_width=True):
                handle_voice(duration)
        with col_t:
            if st.button("✍️ Submit", use_container_width=True, type="primary"):
                if typed.strip():
                    process_question(typed.strip())
                else:
                    st.warning("Type something first.")

        st.divider()
        st.markdown(f"**Whisper:** `{WHISPER_MODEL_SIZE}`")
        st.markdown(f"**LLM:** `{OLLAMA_MODEL}`")

        with st.expander("💡 Example questions"):
            st.markdown(
                "**Simple:**\n"
                "- *Show all critical alerts*\n"
                "- *How many alerts of each severity?*\n\n"
                "**With city lookup (spatial JOIN):**\n"
                "- *Which city did the most recent critical alert come from?*\n"
                "- *Show me alerts in Mumbai sorted by severity*\n"
                "- *How many alerts per city?*\n"
                "- *Average temperature of all HIGH_TEMP alerts*\n"
                "- *Cities with no alerts*\n\n"
                "**Blocked:**\n"
                "- ❌ *Delete all critical alerts*"
            )

    # ============ MAIN AREA ============
    if st.session_state.get("transcript"):
        st.subheader("📝 Your Question")
        st.write(f"_{st.session_state['transcript']}_")

    if st.session_state.get("error"):
        st.error(st.session_state["error"])

    if st.session_state.get("sql"):
        st.subheader("🧾 Generated SQL")
        st.code(st.session_state["sql"], language="sql")

    if st.session_state.get("rows") is not None:
        rows = st.session_state["rows"]
        if rows:
            df_results = pd.DataFrame(rows)
            render_geospatial_map(df_results)
            st.subheader(f"📋 Results ({len(rows)} rows)")
            st.dataframe(df_results, use_container_width=True)
        else:
            st.subheader("📋 Results (0 rows)")
            st.info("No rows matched.")

    if st.session_state.get("status") and not st.session_state.get("error"):
        st.info(st.session_state["status"])

    # Debug
    if st.session_state.get("raw_llm"):
        with st.expander("🐛 Debug: raw LLM output"):
            st.code(st.session_state["raw_llm"], language="sql")
