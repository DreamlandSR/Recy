from fastapi import FastAPI
from app.services.crypto_service import (
    get_market_data,
    get_coin_detail,
    get_coin_history
)

from app.services.technical_service import calculate_sma_ema

app = FastAPI(
    title="Recy API",
    description="Intelligent Crypto Market Insight API",
    version="0.1.0"
)


@app.get("/")
def root():
    return {
        "application": "Recy",
        "message": "Welcome to Recy API",
        "version": "0.1.0"
    }


@app.get("/api/crypto/markets")
async def crypto_markets():
    return await get_market_data()

@app.get("/api/crypto/{coin_id}")
async def crypto_detail(coin_id: str):
    return await get_coin_detail(coin_id)

@app.get("/api/crypto/{coin_id}/history")
async def crypto_history(coin_id: str):
    return await get_coin_history(coin_id)

@app.get("/api/crypto/{coin_id}/technical")
async def crypto_technical(coin_id: str):
    history = await get_coin_history(coin_id)

    prices = history["prices"]

    return calculate_sma_ema(prices)