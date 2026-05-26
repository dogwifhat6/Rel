from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel
from scipy.io import wavfile

from vtsql.config import SAMPLE_RATE, WHISPER_MODEL_SIZE


@lru_cache(maxsize=1)
def load_whisper() -> WhisperModel:
    try:
        return WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    except Exception:
        return WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="default")


def transcribe_wav_path(wav_path: str | Path, language: str | None = None) -> str:
    model = load_whisper()
    kwargs = {"vad_filter": False}
    if language and language.lower() != "auto":
        kwargs["language"] = language
    segments, _ = model.transcribe(str(wav_path), **kwargs)
    return " ".join(seg.text.strip() for seg in segments if seg.text.strip())


def transcribe_upload(data: bytes, filename: str = "audio.wav", language: str | None = None) -> str:
    suffix = Path(filename).suffix.lower() or ".wav"
    wav_path = None
    try:
        fd, wav_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        with open(wav_path, "wb") as f:
            f.write(data)
        return transcribe_wav_path(wav_path, language=language)
    finally:
        if wav_path and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except OSError:
                pass


def transcribe_audio_bytes(data: bytes, samplerate: int = SAMPLE_RATE, language: str | None = None) -> str:
    """Backward-compatible helper for raw PCM WAV bytes."""
    return transcribe_upload(data, filename="audio.wav", language=language)


def transcribe_numpy(samples: np.ndarray, samplerate: int = SAMPLE_RATE, language: str | None = None) -> str:
    wav_path = None
    try:
        fd, wav_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        clipped = np.clip(samples.astype(np.float32), -1.0, 1.0)
        pcm16 = np.int16(np.round(clipped * 32767.0))
        wavfile.write(wav_path, samplerate, pcm16)
        return transcribe_wav_path(wav_path, language=language)
    finally:
        if wav_path and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except OSError:
                pass
