from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class FilterState(BaseModel):
    cities: list[str] = Field(default_factory=list)
    temperature_min: int
    temperature_max: int
    humidity_min: int
    humidity_max: int
    range_min: int
    range_max: int


class DbConfigOverride(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    dbname: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class TextRequest(BaseModel):
    text: str
    previous_filters: Optional[FilterState] = None
    db: Optional[DbConfigOverride] = None


class IntentResponse(BaseModel):
    intent: str
    reason: str
    raw: str


class ExtractFiltersResponse(BaseModel):
    filters: FilterState
    raw: str


class InterpretResponse(BaseModel):
    transcript: str
    blocked: bool
    intent: IntentResponse
    filters: Optional[FilterState] = None
    filters_raw: Optional[str] = None
    message: Optional[str] = None


class QueryRequest(BaseModel):
    filters: FilterState
    db: Optional[DbConfigOverride] = None


class QueryResponse(BaseModel):
    sql: str
    params: list[Any]
    row_count: int
    rows: list[dict[str, Any]]
    normalized_filters: dict[str, Any]


class NLQueryRequest(BaseModel):
    text: str
    previous_filters: Optional[FilterState] = None
    execute: bool = True
    db: Optional[DbConfigOverride] = None


class NLQueryResponse(BaseModel):
    transcript: str
    blocked: bool
    intent: IntentResponse
    filters: Optional[FilterState] = None
    filters_raw: Optional[str] = None
    sql: Optional[str] = None
    params: Optional[list[Any]] = None
    row_count: int = 0
    rows: list[dict[str, Any]] = Field(default_factory=list)
    normalized_filters: Optional[dict[str, Any]] = None
    message: Optional[str] = None


class TranscribeResponse(BaseModel):
    transcript: str


class HealthResponse(BaseModel):
    status: str
    postgres: bool
    ollama: bool
    details: dict[str, str] = Field(default_factory=dict)
