from fastapi import FastAPI, HTTPException
from app.services.crypto_service import (
    get_market_data,
    get_coin_detail,
    get_coin_history,
    get_coin_list,
    resolve_coin_id
)

from app.services.technical_service import calculate_sma_ema
from app.services.scoring_service import calculate_technical_score, calculate_final_score
from app.services.recommendation_service import generate_recommendation
from app.services.news_service import get_crypto_news
from app.services.sentiment_service import analyze_news_sentiment, calculate_sentiment_score

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
async def crypto_technical(coin_id: str, days: int = 365):
    history = await get_coin_history(coin_id, days=days)

    prices = history["prices"]
    volumes = history.get("total_volumes") or []

    return calculate_sma_ema(prices, volumes)

@app.get("/api/crypto/{coin_id}/technical/score")
async def crypto_technical_score(coin_id: str, days: int = 365):
    history = await get_coin_history(coin_id, days=days)

    prices = history["prices"]
    volumes = history.get("total_volumes") or []

    technical_data = calculate_sma_ema(prices, volumes)

    latest_data = technical_data[-1]

    score = calculate_technical_score(latest_data)

    return {
        "coin_id": coin_id,
        "latest_data": latest_data,
        "score": score
    }
    
@app.get("/api/crypto/{coin_id}/recommendation")
async def crypto_recommendation(coin_id: str, days: int = 365):

    history = await get_coin_history(coin_id, days=days)

    prices = history["prices"]
    volumes = history.get("total_volumes") or []

    technical_data = calculate_sma_ema(prices, volumes)

    latest_data = technical_data[-1]

    technical_score = calculate_technical_score(latest_data)

    recommendation = generate_recommendation(
        technical_score["technical_score"],
        technical_score["condition"],
        trend_filter_ok=technical_score["trend_filter_ok"]
    )

    return {
        "coin_id": coin_id,
        "technical": technical_score,
        "recommendation": recommendation
    }
    
@app.get("/api/crypto/{coin_id}/news")
async def crypto_news(coin_id: str):

    news = await get_crypto_news(coin_id)

    return news

@app.get("/api/crypto/{coin_id}/sentiment")
async def crypto_sentiment(coin_id: str):

    news = await get_crypto_news(coin_id)

    articles = news["articles"]

    sentiment_results = analyze_news_sentiment(articles)

    sentiment_score = calculate_sentiment_score(
        sentiment_results
    )

    return {
        "coin_id": coin_id,
        "total_articles": len(sentiment_results),
        "sentiment": sentiment_score,
        "articles": sentiment_results
    }

@app.get("/api/crypto/{coin_id}/analysis")
async def crypto_analysis(coin_id: str, days: int = 365):

    resolved_coin_id = await resolve_coin_id(coin_id)

    if resolved_coin_id is None:
        raise HTTPException(
            status_code=404,
            detail=f"Coin '{coin_id}' tidak ditemukan di CoinGecko."
        )

    history = await get_coin_history(resolved_coin_id, days=days)

    prices = history["prices"]
    volumes = history.get("total_volumes") or []

    technical_data = calculate_sma_ema(prices, volumes)

    latest_data = technical_data[-1]

    technical = calculate_technical_score(
        latest_data
    )

    news = await get_crypto_news(resolved_coin_id)

    articles = news["articles"]

    sentiment_articles = analyze_news_sentiment(
        articles
    )

    sentiment = calculate_sentiment_score(
        sentiment_articles
    )

    final = calculate_final_score(
        technical_score=technical["technical_score"],
        sentiment_score=sentiment["sentiment_score"]
    )

    return {
        "coin_id": resolved_coin_id,
        "technical": technical,
        "sentiment": sentiment,
        "final": final,
        "articles": sentiment_articles
    }

@app.get("/api/coins")
async def coins_list():
    coins = await get_coin_list()

    return {
        "total_coins": len(coins),
        "coins": coins
    }