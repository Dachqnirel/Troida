from fastapi import APIRouter
from api.schemas.tinkoff import (
    StocksRequest, StocksResponse,
    DividendsRequest, DividendsResponse,
)
from api.services.tinkoff import fetch_stocks, fetch_dividends

router = APIRouter()


@router.post("/stocks", response_model=StocksResponse, tags=["Tinkoff"])
async def post_stocks(req: StocksRequest) -> StocksResponse:
    return await fetch_stocks(req)


@router.post("/dividends", response_model=DividendsResponse, tags=["Tinkoff"])
async def post_dividends(req: DividendsRequest) -> DividendsResponse:
    return await fetch_dividends(req)
