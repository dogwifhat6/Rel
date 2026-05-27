from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from vtsql.audio_core import transcribe_upload
from vtsql.db_core import run_select_query
from vtsql.schemas import (
    HealthResponse,
    InterpretResponse,
    NLQueryRequest,
    NLQueryResponse,
    SQLQueryRequest,
    SQLQueryResponse,
    TextRequest,
    TranscribeResponse,
)
from vtsql.services import pipeline_service as svc

app = FastAPI(
    title="Voice-to-SQL API",
    version="2.0.0",
    description=(
        "End-to-end local text/voice-to-SQL pipeline for cities, alerts, and alert_readings. "
        "Direct SQL generation, safety validator, and execution."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _db(body_db: Optional[Any]) -> dict[str, Any] | None:
    if body_db is None:
        return None
    return body_db.as_dict()


@app.get("/health", response_model=HealthResponse, tags=["system"])
@app.get("/healthz", response_model=HealthResponse, tags=["system"])
def health(db_host: Optional[str] = None) -> HealthResponse:
    overrides = {"host": db_host} if db_host else None
    pg_ok, pg_msg = svc.check_postgres(overrides)
    ollama_ok, ollama_msg = svc.check_ollama()
    status = "ok" if pg_ok and ollama_ok else "degraded"
    return HealthResponse(
        status=status,
        postgres=pg_ok,
        ollama=ollama_ok,
        details={"postgres": pg_msg, "ollama": ollama_msg},
    )


@app.get("/v1/cities", response_model=list[str], tags=["metadata"])
def list_cities() -> list[str]:
    try:
        rows, err = run_select_query("SELECT city_name FROM cities ORDER BY city_name")
        if err:
            raise HTTPException(status_code=500, detail=err)
        return [r["city_name"] for r in rows]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/v1/interpret", response_model=InterpretResponse, tags=["pipeline"])
def interpret_endpoint(body: TextRequest) -> InterpretResponse:
    try:
        data = svc.run_interpret(body.text)
        return InterpretResponse(
            transcript=data["transcript"],
            blocked=data["blocked"],
            sql=data["sql"],
            raw_llm=data["raw_llm"],
            message=data["message"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/query", response_model=SQLQueryResponse, tags=["pipeline"])
def query_endpoint(body: SQLQueryRequest) -> SQLQueryResponse:
    try:
        data = svc.run_query(body.sql, _db(body.db))
        return SQLQueryResponse(
            sql=data["sql"],
            row_count=data["row_count"],
            rows=data["rows"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/nl-query", response_model=NLQueryResponse, tags=["pipeline"])
def nl_query_endpoint(body: NLQueryRequest) -> NLQueryResponse:
    try:
        data = svc.run_nl_query(body.text, body.execute, _db(body.db))
        return NLQueryResponse(
            transcript=data["transcript"],
            blocked=data["blocked"],
            sql=data["sql"],
            raw_llm=data["raw_llm"],
            row_count=data["row_count"],
            rows=data["rows"],
            message=data["message"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/transcribe", response_model=TranscribeResponse, tags=["voice"])
async def transcribe_endpoint(
    file: UploadFile = File(...),
    language: str = Form("auto"),
) -> TranscribeResponse:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio file")
    try:
        text = transcribe_upload(
            data,
            filename=file.filename or "audio.wav",
            language=None if language == "auto" else language,
        )
        return TranscribeResponse(transcript=text)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/voice-query", response_model=NLQueryResponse, tags=["voice"])
async def voice_query_endpoint(
    file: UploadFile = File(...),
    language: str = Form("auto"),
    execute: bool = Form(True),
) -> NLQueryResponse:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio file")

    try:
        text = transcribe_upload(
            data,
            filename=file.filename or "audio.wav",
            language=None if language == "auto" else language,
        )
        result = svc.run_nl_query(text, execute=execute)
        return NLQueryResponse(
            transcript=result["transcript"],
            blocked=result["blocked"],
            sql=result["sql"],
            raw_llm=result["raw_llm"],
            row_count=result["row_count"],
            rows=result["rows"],
            message=result["message"],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
