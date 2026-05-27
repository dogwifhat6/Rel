from __future__ import annotations

import pandas as pd
import streamlit as st

from vtsql.audio import record_microphone, transcribe
from vtsql.config import DEFAULT_DURATION, OLLAMA_MODEL, SAMPLE_RATE, WHISPER_MODEL_SIZE
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
        st.subheader(f"📋 Results ({len(rows)} rows)")
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        else:
            st.info("No rows matched.")

    if st.session_state.get("status") and not st.session_state.get("error"):
        st.info(st.session_state["status"])

    # Debug
    if st.session_state.get("raw_llm"):
        with st.expander("🐛 Debug: raw LLM output"):
            st.code(st.session_state["raw_llm"], language="sql")
