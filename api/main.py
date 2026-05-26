from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from vtsql.audio_core import transcribe_upload
from vtsql.db_core import fetch_distinct_cities
from vtsql.schemas import (
    ExtractFiltersResponse,
    FilterState,
    HealthResponse,
    IntentResponse,
    InterpretResponse,
    NLQueryRequest,
    NLQueryResponse,
    QueryRequest,
    QueryResponse,
    TextRequest,
    TranscribeResponse,
)
from vtsql.services import pipeline_service as svc

app = FastAPI(
    title="Voice-to-SQL API",
    version="1.0.0",
    description=(
        "End-to-end local NL-to-SQL pipeline for city_metrics. "
        "Intent guard, filter extraction, parameterized SELECT execution, and optional voice transcription."
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
        return list(fetch_distinct_cities())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/v1/intent", response_model=IntentResponse, tags=["pipeline"])
def intent_endpoint(body: TextRequest) -> IntentResponse:
    try:
        data = svc.run_intent(body.text)
        return IntentResponse(**data)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Invalid JSON from model: {exc}") from exc


@app.post("/v1/extract-filters", response_model=ExtractFiltersResponse, tags=["pipeline"])
def extract_filters_endpoint(body: TextRequest) -> ExtractFiltersResponse:
    try:
        data = svc.run_extract_filters(body.text, body.previous_filters, _db(body.db))
        return ExtractFiltersResponse(**data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Invalid JSON from model: {exc}") from exc


@app.post("/v1/interpret", response_model=InterpretResponse, tags=["pipeline"])
def interpret_endpoint(body: TextRequest) -> InterpretResponse:
    try:
        data = svc.run_interpret(body.text, body.previous_filters, _db(body.db))
        return InterpretResponse(
            transcript=data["transcript"],
            blocked=data["blocked"],
            intent=IntentResponse(**data["intent"]),
            filters=data.get("filters"),
            filters_raw=data.get("filters_raw"),
            message=data.get("message"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Invalid JSON from model: {exc}") from exc


@app.post("/v1/query", response_model=QueryResponse, tags=["pipeline"])
def query_endpoint(body: QueryRequest) -> QueryResponse:
    try:
        data = svc.run_query(body.filters, _db(body.db))
        return QueryResponse(**data)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/nl-query", response_model=NLQueryResponse, tags=["pipeline"])
def nl_query_endpoint(body: NLQueryRequest) -> NLQueryResponse:
    try:
        data = svc.run_nl_query(body.text, body.previous_filters, body.execute, _db(body.db))
        return NLQueryResponse(
            transcript=data["transcript"],
            blocked=data["blocked"],
            intent=IntentResponse(**data["intent"]),
            filters=data.get("filters"),
            filters_raw=data.get("filters_raw"),
            sql=data.get("sql"),
            params=data.get("params"),
            row_count=data.get("row_count", 0),
            rows=data.get("rows", []),
            normalized_filters=data.get("normalized_filters"),
            message=data.get("message"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Invalid JSON from model: {exc}") from exc


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
    previous_filters: Optional[str] = Form(None),
) -> NLQueryResponse:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio file")

    prev: Optional[FilterState] = None
    if previous_filters:
        try:
            prev = FilterState(**json.loads(previous_filters))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid previous_filters JSON: {exc}") from exc

    try:
        text = transcribe_upload(
            data,
            filename=file.filename or "audio.wav",
            language=None if language == "auto" else language,
        )
        result = svc.run_nl_query(text, prev, execute=execute)
        return NLQueryResponse(
            transcript=result["transcript"],
            blocked=result["blocked"],
            intent=IntentResponse(**result["intent"]),
            filters=result.get("filters"),
            filters_raw=result.get("filters_raw"),
            sql=result.get("sql"),
            params=result.get("params"),
            row_count=result.get("row_count", 0),
            rows=result.get("rows", []),
            normalized_filters=result.get("normalized_filters"),
            message=result.get("message"),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Invalid JSON from model: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
