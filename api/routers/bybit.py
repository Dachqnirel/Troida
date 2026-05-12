from fastapi import APIRouter
from api.schemas.bybit import CandlesRequest, CandlesResponse
from api.services.bybit import fetch_candles

router = APIRouter()


@router.post("/candles", response_model=CandlesResponse, tags=["Bybit"])
def post_candles(req: CandlesRequest) -> CandlesResponse:
    return fetch_candles(req)
