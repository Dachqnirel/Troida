import pytest
from pydantic import ValidationError
from api.schemas.bybit import CandlesRequest


def test_symbol_is_uppercased():
    req = CandlesRequest(symbol="btcusdt", category="spot", interval="60")
    assert req.symbol == "BTCUSDT"


def test_valid_request_defaults():
    req = CandlesRequest(symbol="ETHUSDT", category="linear", interval="D")
    assert req.limit == 200
    assert req.start is None
    assert req.end is None


def test_invalid_category_raises():
    with pytest.raises(ValidationError):
        CandlesRequest(symbol="BTC", category="options", interval="60")


def test_invalid_interval_raises():
    with pytest.raises(ValidationError):
        CandlesRequest(symbol="BTC", category="spot", interval="999")


def test_limit_above_200_raises():
    with pytest.raises(ValidationError):
        CandlesRequest(symbol="BTC", category="spot", interval="60", limit=201)


def test_limit_below_1_raises():
    with pytest.raises(ValidationError):
        CandlesRequest(symbol="BTC", category="spot", interval="60", limit=0)


def test_invalid_start_date_raises():
    with pytest.raises(ValidationError):
        CandlesRequest(symbol="BTC", category="spot", interval="60", start="01/01/2024")


def test_valid_datetime_start():
    req = CandlesRequest(symbol="BTC", category="spot", interval="60", start="2024-01-01 12:00:00")
    assert req.start == "2024-01-01 12:00:00"


def test_valid_date_only_start():
    req = CandlesRequest(symbol="BTC", category="spot", interval="60", start="2024-01-01")
    assert req.start == "2024-01-01"


def test_valid_end_date():
    req = CandlesRequest(symbol="BTC", category="spot", interval="60", end="2024-12-31")
    assert req.end == "2024-12-31"


def test_invalid_end_date_raises():
    with pytest.raises(ValidationError):
        CandlesRequest(symbol="BTC", category="spot", interval="60", end="31/12/2024")


from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from api.schemas.bybit import CandlesResponse, Candle
from api.services.bybit import fetch_candles

_SAMPLE_CANDLE = {
    "timestamp": 1700000000000,
    "datetime": "2024-01-01 00:00:00",
    "open": 42000.0, "high": 42500.0, "low": 41800.0,
    "close": 42300.0, "volume": 12.5, "turnover": 525000.0,
}


def test_fetch_candles_success():
    req = CandlesRequest(symbol="BTCUSDT", category="spot", interval="60")
    with patch("api.services.bybit.BybitCandles") as MockClient, \
         patch("api.services.bybit.AnomalyDetector") as MockDetector:
        MockClient.return_value.get_candles.return_value = [_SAMPLE_CANDLE]
        MockDetector.return_value.check_and_fix.return_value = ([_SAMPLE_CANDLE], 0)
        result = fetch_candles(req)
    assert result.symbol == "BTCUSDT"
    assert result.count == 1
    assert result.anomalies_removed == 0
    assert result.candles[0].timestamp == 1700000000000


def test_fetch_candles_anomalies_removed():
    req = CandlesRequest(symbol="BTCUSDT", category="spot", interval="60")
    with patch("api.services.bybit.BybitCandles") as MockClient, \
         patch("api.services.bybit.AnomalyDetector") as MockDetector:
        MockClient.return_value.get_candles.return_value = [_SAMPLE_CANDLE, _SAMPLE_CANDLE]
        MockDetector.return_value.check_and_fix.return_value = ([_SAMPLE_CANDLE], 1)
        result = fetch_candles(req)
    assert result.count == 1
    assert result.anomalies_removed == 1


def test_fetch_candles_returns_none_raises_502():
    req = CandlesRequest(symbol="BTCUSDT", category="spot", interval="60")
    with patch("api.services.bybit.BybitCandles") as MockClient, \
         patch("api.services.bybit.AnomalyDetector"):
        MockClient.return_value.get_candles.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            fetch_candles(req)
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["error"] == "no_data"


def test_fetch_candles_exception_raises_502():
    req = CandlesRequest(symbol="BTCUSDT", category="spot", interval="60")
    with patch("api.services.bybit.BybitCandles") as MockClient:
        MockClient.return_value.get_candles.side_effect = Exception("connection refused")
        with pytest.raises(HTTPException) as exc_info:
            fetch_candles(req)
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["error"] == "bybit_error"
    assert "connection refused" in exc_info.value.detail["message"]


async def test_post_candles_success(client):
    mock_response = CandlesResponse(
        symbol="BTCUSDT", category="spot", interval="60",
        count=1, anomalies_removed=0,
        candles=[Candle(**_SAMPLE_CANDLE)],
    )
    with patch("api.routers.bybit.fetch_candles", return_value=mock_response):
        response = await client.post("/bybit/candles", json={
            "symbol": "btcusdt", "category": "spot", "interval": "60"
        })
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "BTCUSDT"
    assert body["count"] == 1
    assert len(body["candles"]) == 1


async def test_post_candles_invalid_interval(client):
    response = await client.post("/bybit/candles", json={
        "symbol": "BTCUSDT", "category": "spot", "interval": "999"
    })
    assert response.status_code == 422
    assert "error" in response.json()


async def test_post_candles_invalid_category(client):
    response = await client.post("/bybit/candles", json={
        "symbol": "BTCUSDT", "category": "options", "interval": "60"
    })
    assert response.status_code == 422


async def test_post_candles_missing_required_field(client):
    response = await client.post("/bybit/candles", json={
        "symbol": "BTCUSDT", "category": "spot"
        # missing interval
    })
    assert response.status_code == 422
