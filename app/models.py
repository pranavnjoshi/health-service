from __future__ import annotations
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

# --- General Authentication and Data Models ---

class TokenModel(BaseModel):
    """Container for OAuth2 tokens."""
    access_token: str
    refresh_token: Optional[str]
    expires_at: Optional[int]
    scope: Optional[str]
    token_type: Optional[str]

class MetricPoint(BaseModel):
    """Standardized data point for time-series metrics like steps or calories."""
    timestamp: int
    value: float
    extra: Optional[Dict[str, Any]] = None

# --- Fitbit Specific Sleep Models ---

class SleepLevelSummaryItem(BaseModel):
    """Minutes and counts for a specific sleep stage (e.g., REM or Deep)."""
    count: Optional[int] = None
    minutes: Optional[int] = None
    thirtyDayAvgMinutes: Optional[int] = None

class SleepLevelSummary(BaseModel):
    """Summary of all stages recorded during a sleep session."""
    # Modern Stage-based sleep
    deep: Optional[SleepLevelSummaryItem] = None
    light: Optional[SleepLevelSummaryItem] = None
    rem: Optional[SleepLevelSummaryItem] = None
    wake: Optional[SleepLevelSummaryItem] = None
    # Classic mode sleep
    asleep: Optional[SleepLevelSummaryItem] = None
    restless: Optional[SleepLevelSummaryItem] = None
    awake: Optional[SleepLevelSummaryItem] = None

class SleepLevelData(BaseModel):
    """A specific minute-by-minute interval of a sleep stage."""
    dateTime: str
    level: str
    seconds: int

class SleepLevels(BaseModel):
    """The root container for sleep levels, including summary and timeline data."""
    summary: Optional[SleepLevelSummary] = None
    data: Optional[List[SleepLevelData]] = []
    shortData: Optional[List[SleepLevelData]] = []

class FitbitSleepLog(BaseModel):
    """The full Fitbit sleep record as returned by the /sleep API."""
    dateOfSleep: str
    startTime: str
    endTime: str
    type: str  # "stages" or "classic"
    levels: SleepLevels
    duration: Optional[int] = None
    efficiency: Optional[int] = None
    isMainSleep: Optional[bool] = None
    logId: Optional[int] = None
    minutesAsleep: Optional[int] = None
    minutesAwake: Optional[int] = None
    timeInBed: Optional[int] = None

# --- General Response Models ---

class SleepSegment(BaseModel):
    """Simplified sleep entry for general cross-provider use."""
    start_time: int
    end_time: int
    type: str

class MetricsResponse(BaseModel):
    """The root response object returned by the /data endpoint."""
    provider: str
    user_id: str
    # metrics defaults to an empty dict for safe access
    metrics: Dict[str, Any] = Field(default_factory=dict)
    # sleep defaults to an empty list to avoid null responses
    sleep: List[SleepSegment] = Field(default_factory=list)