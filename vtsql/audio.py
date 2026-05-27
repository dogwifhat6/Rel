from __future__ import annotations

import numpy as np
import streamlit as st
from faster_whisper import WhisperModel

from vtsql.audio_core import load_whisper as _load_whisper_core
from vtsql.audio_core import transcribe_numpy
from vtsql.config import SAMPLE_RATE


@st.cache_resource(show_spinner="Loading Whisper model (first load may download weights)...")
def load_whisper() -> WhisperModel:
    return _load_whisper_core()


def record_microphone(duration_sec: float, samplerate: int) -> np.ndarray:
    try:
        import sounddevice as sd
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            f"sounddevice or PortAudio error: {exc}. "
            "Please make sure PortAudio is installed on your system (e.g., 'brew install portaudio' on macOS "
            "or 'apt-get install portaudio19-dev' on Ubuntu/Debian)."
        ) from exc

    frames = max(1, int(duration_sec * samplerate))
    audio = sd.rec(frames, samplerate=samplerate, channels=1, dtype=np.float32)
    sd.wait()
    return audio.reshape(-1)


def transcribe(samples: np.ndarray, samplerate: int) -> str:
    _ = load_whisper()
    return transcribe_numpy(samples, samplerate=samplerate)
