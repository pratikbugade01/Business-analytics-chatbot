from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ResponseType = Literal["number", "string", "dataframe", "chart", "chart_spec", "error"]


class DatasetResponse(BaseModel):
    session_id: str
    filename: str
    rows: int
    columns: list[str]
    created_at: datetime


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    session_id: str
    type: ResponseType
    value: Any = None
    message: str | None = None
    chart_url: str | None = None
    created_at: datetime


class HealthResponse(BaseModel):
    status: str
    llm_configured: bool

