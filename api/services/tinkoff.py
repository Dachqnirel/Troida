from datetime import datetime, timezone
from typing import Optional
import pandas as pd
from fastapi import HTTPException
from api.schemas.tinkoff import (
    StocksRequest, StocksResponse, StockCandle,
    DividendsRequest, DividendsResponse, Dividend,
)


def _parse_dt(date_str: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"invalid date: {date_str}")


def _ts_to_str(val) -> Optional[str]:
    if val is None or str(val) == "None":
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    return str(val)


def _nullable_float(val) -> Optional[float]:
    if val is None or str(val) == "None":
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


async def fetch_stocks(req: StocksRequest) -> StocksResponse:
    from packages.API.T_InvestAPI import tAPI

    from_dt = _parse_dt(req.from_date)
    to_dt = _parse_dt(req.to_date)

    try:
        df = await tAPI.download_candles(req.ticker, req.interval, from_dt, to_dt)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": "tinkoff_error", "message": str(exc)},
        )

    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        raise HTTPException(
            status_code=502,
            detail={"error": "no_data", "message": f"Tinkoff returned no candles for {req.ticker}"},
        )

    candles = [
        StockCandle(
            datetime=_ts_to_str(rec.get("datetime")) or "",
            open=float(rec["open"]),
            high=float(rec["high"]),
            low=float(rec["low"]),
            close=float(rec["close"]),
            volume=float(rec["volume"]),
        )
        for rec in df.to_dict(orient="records")
    ]

    return StocksResponse(ticker=req.ticker, interval=req.interval, count=len(candles), candles=candles)


async def fetch_dividends(req: DividendsRequest) -> DividendsResponse:
    from packages.API.T_InvestAPI import tAPI

    from_dt = _parse_dt(req.from_date)
    to_dt = _parse_dt(req.to_date)

    try:
        df = await tAPI.download_dividends(req.ticker, from_dt, to_dt)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": "tinkoff_error", "message": str(exc)},
        )

    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        raise HTTPException(
            status_code=502,
            detail={"error": "no_data", "message": f"Tinkoff returned no dividends for {req.ticker}"},
        )

    dividends = [
        Dividend(
            declared_date=_ts_to_str(rec.get("declared_date")),
            last_buy_date=_ts_to_str(rec.get("last_buy_date")),
            payment_date=_ts_to_str(rec.get("payment_date")),
            dividend_net=_nullable_float(rec.get("dividend_net")),
            dividend_gross=_nullable_float(rec.get("dividend_gross")),
            close_price=_nullable_float(rec.get("close_price")),
            yield_value=_nullable_float(rec.get("yield_value")),
            regularity=_ts_to_str(rec.get("regularity")),
        )
        for rec in df.to_dict(orient="records")
    ]

    return DividendsResponse(ticker=req.ticker, count=len(dividends), dividends=dividends)
