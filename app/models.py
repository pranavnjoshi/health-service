from __future__ import annotations
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class TokenModel(BaseModel):
    access_token: str
    refresh_token: Optional[str]
    expires_at: Optional[int]  # unix epoch seconds
    scope: Optional[str]
    token_type: Optional[str]


class MetricPoint(BaseModel):
    timestamp: int
    value: float
    extra: Optional[Dict[str, Any]] = None


class SleepSegment(BaseModel):
    start_time: int
    end_time: int
    type: str


class MetricsResponse(BaseModel):
    provider: str
    user_id: str
    metrics: Dict[str, List[MetricPoint]] = Field(default_factory=dict)
    sleep: Optional[List[SleepSegment]] = None
