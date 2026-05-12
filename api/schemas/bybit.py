from __future__ import annotations
from datetime import datetime as _dt
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class Category(str, Enum):
    spot = "spot"
    linear = "linear"
    inverse = "inverse"


_VALID_INTERVALS = frozenset({"1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W", "M"})


class CandlesRequest(BaseModel):
    symbol: str
    category: Category
    interval: str
    limit: int = Field(default=200, ge=1, le=200)
    start: Optional[str] = None
    end: Optional[str] = None

    @field_validator("symbol")
    @classmethod
    def upper_symbol(cls, v: str) -> str:
        return v.upper()

    @field_validator("interval")
    @classmethod
    def valid_interval(cls, v: str) -> str:
        if v not in _VALID_INTERVALS:
            raise ValueError(
                f"interval '{v}' is not valid. Allowed: {', '.join(sorted(_VALID_INTERVALS))}"
            )
        return v

    @field_validator("start", "end")
    @classmethod
    def valid_date(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                _dt.strptime(v, fmt)
                return v
            except ValueError:
                continue
        raise ValueError(f"date '{v}' must be YYYY-MM-DD or YYYY-MM-DD HH:MM:SS")


class Candle(BaseModel):
    timestamp: int
    datetime: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float


class CandlesResponse(BaseModel):
    symbol: str
    category: str
    interval: str
    count: int
    anomalies_removed: int
    candles: list[Candle]
