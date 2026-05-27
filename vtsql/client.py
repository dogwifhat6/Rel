from __future__ import annotations

from typing import Any, Optional

import requests


class VoiceToSQLClient:
    """Thin HTTP client for integrating Voice-to-SQL into other apps."""

    def __init__(self, base_url: str = "http://localhost:8000", timeout_sec: int = 180):
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec

    def health(self) -> dict[str, Any]:
        r = requests.get(f"{self.base_url}/health", timeout=10)
        r.raise_for_status()
        return r.json()

    def cities(self) -> list[str]:
        r = requests.get(f"{self.base_url}/v1/cities", timeout=30)
        r.raise_for_status()
        return r.json()

    def intent(self, text: str) -> dict[str, Any]:
        r = requests.post(f"{self.base_url}/v1/intent", json={"text": text}, timeout=self.timeout_sec)
        r.raise_for_status()
        return r.json()

    def extract_filters(
        self, text: str, previous_filters: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": text}
        if previous_filters is not None:
            payload["previous_filters"] = previous_filters
        r = requests.post(f"{self.base_url}/v1/extract-filters", json=payload, timeout=self.timeout_sec)
        r.raise_for_status()
        return r.json()

    def interpret(self, text: str, previous_filters: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": text}
        if previous_filters is not None:
            payload["previous_filters"] = previous_filters
        r = requests.post(f"{self.base_url}/v1/interpret", json=payload, timeout=self.timeout_sec)
        r.raise_for_status()
        return r.json()

    def query(self, filters: dict[str, Any]) -> dict[str, Any]:
        r = requests.post(f"{self.base_url}/v1/query", json={"filters": filters}, timeout=self.timeout_sec)
        r.raise_for_status()
        return r.json()

    def nl_query(
        self,
        text: str,
        previous_filters: Optional[dict[str, Any]] = None,
        execute: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": text, "execute": execute}
        if previous_filters is not None:
            payload["previous_filters"] = previous_filters
        r = requests.post(f"{self.base_url}/v1/nl-query", json=payload, timeout=self.timeout_sec)
        r.raise_for_status()
        return r.json()

    def transcribe(self, audio_path: str, language: str = "auto") -> str:
        with open(audio_path, "rb") as f:
            r = requests.post(
                f"{self.base_url}/v1/transcribe",
                files={"file": (audio_path, f)},
                data={"language": language},
                timeout=self.timeout_sec,
            )
        r.raise_for_status()
        return r.json()["transcript"]

    def voice_query(
        self,
        audio_path: str,
        previous_filters: Optional[dict[str, Any]] = None,
        execute: bool = True,
        language: str = "auto",
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"language": language, "execute": str(execute).lower()}
        if previous_filters is not None:
            import json

            data["previous_filters"] = json.dumps(previous_filters)
        with open(audio_path, "rb") as f:
            r = requests.post(
                f"{self.base_url}/v1/voice-query",
                files={"file": (audio_path, f)},
                data=data,
                timeout=self.timeout_sec,
            )
        r.raise_for_status()
        return r.json()
