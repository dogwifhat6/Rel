from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


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
    db: Optional[DbConfigOverride] = None


class InterpretResponse(BaseModel):
    transcript: str
    blocked: bool
    sql: Optional[str] = None
    raw_llm: Optional[str] = None
    message: Optional[str] = None


class SQLQueryRequest(BaseModel):
    sql: str
    db: Optional[DbConfigOverride] = None


class SQLQueryResponse(BaseModel):
    sql: str
    row_count: int
    rows: list[dict[str, Any]]


class NLQueryRequest(BaseModel):
    text: str
    execute: bool = True
    db: Optional[DbConfigOverride] = None


class NLQueryResponse(BaseModel):
    transcript: str
    blocked: bool
    sql: Optional[str] = None
    raw_llm: Optional[str] = None
    row_count: int = 0
    rows: list[dict[str, Any]] = Field(default_factory=list)
    message: Optional[str] = None


class TranscribeResponse(BaseModel):
    transcript: str


class HealthResponse(BaseModel):
    status: str
    postgres: bool
    ollama: bool
    details: dict[str, str] = Field(default_factory=dict)
