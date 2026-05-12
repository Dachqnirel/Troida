from datetime import datetime, timezone
from fastapi import HTTPException
from bybit_parser.byparser import BybitCandles, AnomalyDetector, INTERVAL_MINUTES
from api.schemas.bybit import CandlesRequest, CandlesResponse, Candle


def _to_ms(date_str: str) -> int:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            continue
    raise ValueError(f"invalid date: {date_str}")


def fetch_candles(req: CandlesRequest) -> CandlesResponse:
    start_ms = _to_ms(req.start) if req.start else None
    end_ms = _to_ms(req.end) if req.end else None

    try:
        raw = BybitCandles().get_candles(
            symbol=req.symbol,
            interval=req.interval,
            category=req.category.value,
            limit=req.limit,
            start_ms=start_ms,
            end_ms=end_ms,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": "bybit_error", "message": str(exc)},
        )

    if raw is None:
        raise HTTPException(
            status_code=502,
            detail={"error": "no_data", "message": "Bybit returned no candles for the given parameters"},
        )

    interval_minutes = INTERVAL_MINUTES[req.interval]
    cleaned, removed = AnomalyDetector(interval_minutes).check_and_fix(raw)

    return CandlesResponse(
        symbol=req.symbol,
        category=req.category.value,
        interval=req.interval,
        count=len(cleaned),
        anomalies_removed=removed,
        candles=[Candle(**c) for c in cleaned],
    )
