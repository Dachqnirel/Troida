import pytest
import pandas as pd
from pydantic import ValidationError
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException
from api.schemas.tinkoff import (
    StocksRequest, StocksResponse, DividendsRequest, DividendsResponse,
)


# ── Schema validation tests ──────────────────────────────────────────

def test_stocks_ticker_uppercased():
    req = StocksRequest(ticker="sber", interval="2H", from_date="2024-01-01", to_date="2025-01-01")
    assert req.ticker == "SBER"


def test_stocks_defaults():
    req = StocksRequest(ticker="SBER", interval="2H", from_date="2024-01-01", to_date="2025-01-01")
    assert req.instrument_type == 2


def test_stocks_invalid_interval_raises():
    with pytest.raises(ValidationError):
        StocksRequest(ticker="SBER", interval="999", from_date="2024-01-01", to_date="2025-01-01")


def test_stocks_invalid_date_raises():
    with pytest.raises(ValidationError):
        StocksRequest(ticker="SBER", interval="2H", from_date="01-01-2024", to_date="2025-01-01")


def test_dividends_ticker_uppercased():
    req = DividendsRequest(ticker="vtbr", from_date="2024-01-01", to_date="2025-01-01")
    assert req.ticker == "VTBR"


def test_dividends_invalid_date_raises():
    with pytest.raises(ValidationError):
        DividendsRequest(ticker="SBER", from_date="not-a-date", to_date="2025-01-01")


def test_dividends_datetime_format_accepted():
    req = DividendsRequest(ticker="SBER", from_date="2024-01-01 00:00:00", to_date="2025-01-01 00:00:00")
    assert req.from_date == "2024-01-01 00:00:00"


# ── Service unit tests: stocks ───────────────────────────────────────

from api.services.tinkoff import fetch_stocks, fetch_dividends

_SAMPLE_STOCKS_DF = pd.DataFrame([{
    "datetime": pd.Timestamp("2024-10-21 10:00:00"),
    "open": 285.5, "high": 287.0, "low": 284.0,
    "close": 286.2, "volume": 150000,
}])

_SAMPLE_DIVIDENDS_DF = pd.DataFrame([{
    "declared_date": pd.Timestamp("2024-06-15"),
    "last_buy_date": pd.Timestamp("2024-07-10"),
    "payment_date": pd.Timestamp("2024-07-25"),
    "dividend_net": 33.45,
    "dividend_gross": 38.44,
    "close_price": 285.5,
    "yield_value": 0.1172,
    "regularity": "Annual",
}])


async def test_fetch_stocks_success():
    req = StocksRequest(ticker="SBER", interval="2H", from_date="2024-10-21", to_date="2025-10-21")
    with patch("packages.API.T_InvestAPI.tAPI.download_candles", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = _SAMPLE_STOCKS_DF
        result = await fetch_stocks(req)
    assert result.ticker == "SBER"
    assert result.count == 1
    assert result.candles[0].open == 285.5
    assert result.candles[0].datetime == "2024-10-21 10:00:00"


async def test_fetch_stocks_no_data_raises_502():
    req = StocksRequest(ticker="SBER", interval="2H", from_date="2024-10-21", to_date="2025-10-21")
    with patch("packages.API.T_InvestAPI.tAPI.download_candles", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await fetch_stocks(req)
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["error"] == "no_data"


async def test_fetch_stocks_exception_raises_502():
    req = StocksRequest(ticker="SBER", interval="2H", from_date="2024-10-21", to_date="2025-10-21")
    with patch("packages.API.T_InvestAPI.tAPI.download_candles", new_callable=AsyncMock) as mock_fn:
        mock_fn.side_effect = Exception("grpc error")
        with pytest.raises(HTTPException) as exc_info:
            await fetch_stocks(req)
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["error"] == "tinkoff_error"


# ── Service unit tests: dividends ────────────────────────────────────

async def test_fetch_dividends_success():
    req = DividendsRequest(ticker="SBER", from_date="2024-01-01", to_date="2025-01-01")
    with patch("packages.API.T_InvestAPI.tAPI.download_dividends", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = _SAMPLE_DIVIDENDS_DF
        result = await fetch_dividends(req)
    assert result.ticker == "SBER"
    assert result.count == 1
    assert result.dividends[0].dividend_net == 33.45
    assert result.dividends[0].declared_date == "2024-06-15 00:00:00"


async def test_fetch_dividends_no_data_raises_502():
    req = DividendsRequest(ticker="SBER", from_date="2024-01-01", to_date="2025-01-01")
    with patch("packages.API.T_InvestAPI.tAPI.download_dividends", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await fetch_dividends(req)
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["error"] == "no_data"


async def test_fetch_dividends_exception_raises_502():
    req = DividendsRequest(ticker="SBER", from_date="2024-01-01", to_date="2025-01-01")
    with patch("packages.API.T_InvestAPI.tAPI.download_dividends", new_callable=AsyncMock) as mock_fn:
        mock_fn.side_effect = Exception("rate limited")
        with pytest.raises(HTTPException) as exc_info:
            await fetch_dividends(req)
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["error"] == "tinkoff_error"


# ── HTTP integration tests ───────────────────────────────────────────

async def test_post_stocks_success(client):
    mock_response = StocksResponse(
        ticker="SBER", interval="2H", count=1,
        candles=[{"datetime": "2024-10-21 10:00:00", "open": 285.5,
                  "high": 287.0, "low": 284.0, "close": 286.2, "volume": 150000}],
    )
    with patch("api.routers.tinkoff.fetch_stocks", new_callable=AsyncMock, return_value=mock_response):
        response = await client.post("/tinkoff/stocks", json={
            "ticker": "sber", "interval": "2H",
            "from_date": "2024-10-21", "to_date": "2025-10-21"
        })
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "SBER"
    assert body["count"] == 1


async def test_post_stocks_invalid_interval(client):
    response = await client.post("/tinkoff/stocks", json={
        "ticker": "SBER", "interval": "999",
        "from_date": "2024-10-21", "to_date": "2025-10-21"
    })
    assert response.status_code == 422
    assert "error" in response.json()


async def test_post_dividends_success(client):
    mock_response = DividendsResponse(
        ticker="SBER", count=1,
        dividends=[{
            "declared_date": "2024-06-15 00:00:00",
            "last_buy_date": "2024-07-10 00:00:00",
            "payment_date": "2024-07-25 00:00:00",
            "dividend_net": 33.45,
            "dividend_gross": 38.44,
            "close_price": 285.5,
            "yield_value": 0.1172,
            "regularity": "Annual",
        }],
    )
    with patch("api.routers.tinkoff.fetch_dividends", new_callable=AsyncMock, return_value=mock_response):
        response = await client.post("/tinkoff/dividends", json={
            "ticker": "sber", "from_date": "2024-01-01", "to_date": "2025-01-01"
        })
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "SBER"
    assert body["dividends"][0]["dividend_net"] == 33.45


async def test_post_dividends_invalid_date(client):
    response = await client.post("/tinkoff/dividends", json={
        "ticker": "SBER", "from_date": "not-a-date", "to_date": "2025-01-01"
    })
    assert response.status_code == 422
