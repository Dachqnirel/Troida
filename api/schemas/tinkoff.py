from __future__ import annotations
from datetime import datetime as _dt
from typing import Optional
from pydantic import BaseModel, field_validator


_VALID_TINKOFF_INTERVALS = frozenset({
    "5S", "10S", "30S",
    "1M", "2M", "3M", "5M", "10M", "15M",
    "1H", "2H", "4H",
    "1D", "1W", "M",
})


def _check_date(v: str) -> str:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            _dt.strptime(v, fmt)
            return v
        except ValueError:
            continue
    raise ValueError(f"date '{v}' must be YYYY-MM-DD or YYYY-MM-DD HH:MM:SS")


class StocksRequest(BaseModel):
    ticker: str
    interval: str
    from_date: str
    to_date: str
    instrument_type: int = 2

    @field_validator("ticker")
    @classmethod
    def upper_ticker(cls, v: str) -> str:
        return v.upper()

    @field_validator("interval")
    @classmethod
    def valid_interval(cls, v: str) -> str:
        if v not in _VALID_TINKOFF_INTERVALS:
            raise ValueError(
                f"interval '{v}' is not valid. Allowed: {', '.join(sorted(_VALID_TINKOFF_INTERVALS))}"
            )
        return v

    @field_validator("from_date", "to_date")
    @classmethod
    def valid_date(cls, v: str) -> str:
        return _check_date(v)


class StockCandle(BaseModel):
    datetime: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class StocksResponse(BaseModel):
    ticker: str
    interval: str
    count: int
    candles: list[StockCandle]


class DividendsRequest(BaseModel):
    ticker: str
    from_date: str
    to_date: str

    @field_validator("ticker")
    @classmethod
    def upper_ticker(cls, v: str) -> str:
        return v.upper()

    @field_validator("from_date", "to_date")
    @classmethod
    def valid_date(cls, v: str) -> str:
        return _check_date(v)


class Dividend(BaseModel):
    declared_date: Optional[str] = None
    last_buy_date: Optional[str] = None
    payment_date: Optional[str] = None
    dividend_net: Optional[float] = None
    dividend_gross: Optional[float] = None
    close_price: Optional[float] = None
    yield_value: Optional[float] = None
    regularity: Optional[str] = None


class DividendsResponse(BaseModel):
    ticker: str
    count: int
    dividends: list[Dividend]
