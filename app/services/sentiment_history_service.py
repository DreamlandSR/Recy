"""Layanan sentimen historis untuk backtest.

Dua sumber:

1. Fear & Greed Index (alternative.me)
   - harian, tersedia penuh 90 hari, gratis tanpa API key
   - skala 0-100, langsung sebanding dengan sentiment_score Recy
   - sifatnya market-wide (bukan per-koin)

2. GNews + FinBERT
   - sentimen per-koin dari berita harian
   - arsip free plan GNews hanya ~30 hari terakhir (diverifikasi)
   - kuota 100 request/hari -> hasil per hari di-cache ke JSON

Kedua sumber di-cache ke JSON agar run bisa direproduksi dan hemat kuota.
"""

import asyncio
import json
import os
from datetime import date, datetime, timedelta, timezone

import httpx

from app.services.news_service import get_crypto_news

FNG_URL = "https://api.alternative.me/fng/"

# Jeda antar request GNews (free plan ~1 req/detik)
GNEWS_DELAY_SECONDS = 0.7


def _load_json(path: str):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _save_json(path: str, payload):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)


# =====================================================================
# 1. Fear & Greed Index (market-wide, 90 hari)
# =====================================================================

async def get_fng_history(
    days: int = 90, cache_path: str = None, force: bool = False
) -> dict:
    """Ambil Fear & Greed Index harian.

    Returns
    -------
    dict {date_iso: {"score": float 0-100, "classification": str}}
    """
    if cache_path and not force:
        cached = _load_json(cache_path)
        if cached and len(cached.get("series", {})) >= days:
            return cached["series"]

    params = {"limit": days, "format": "json"}
    async with httpx.AsyncClient(trust_env=False, timeout=30.0) as client:
        response = await client.get(FNG_URL, params=params)
    response.raise_for_status()
    payload = response.json()

    series = {}
    for item in payload.get("data", []):
        ts = int(item["timestamp"])
        day = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        series[day] = {
            "score": float(item["value"]),
            "classification": item.get("value_classification"),
        }

    if not series:
        raise RuntimeError("Fear & Greed Index tidak mengembalikan data")

    if cache_path:
        _save_json(
            cache_path,
            {
                "source": "alternative.me",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "days": days,
                "series": series,
            },
        )

    return series


# =====================================================================
# 2. GNews + FinBERT (per koin, arsip ~30 hari)
# =====================================================================

def _daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


# Query pencarian berita per koin: coin_id CoinGecko tidak selalu muncul
# di artikel (mis. "binancecoin" -> artikel menulis "BNB"/"Binance").
NEWS_QUERY_BY_COIN = {
    "binancecoin": "BNB",
}


async def _fetch_articles_for_day(
    coin_id: str, day: date, cache_path: str
) -> dict:
    """Ambil artikel 1 hari (00:00-23:59 UTC) dengan cache per hari."""
    cached = _load_json(cache_path)
    if cached is not None and cached.get("status") == "ok":
        return cached

    from_iso = f"{day.isoformat()}T00:00:00Z"
    to_iso = f"{day.isoformat()}T23:59:59Z"

    try:
        news = await get_crypto_news(
            coin_id,
            query=NEWS_QUERY_BY_COIN.get(coin_id),
            max_results=10,
            from_=from_iso,
            to=to_iso,
            sortby="publishedAt",
        )
        result = {
            "status": "ok",
            "date": day.isoformat(),
            "articles": news.get("articles", []),
        }
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        result = {
            "status": "error",
            "date": day.isoformat(),
            "http_status": status,
            "articles": [],
        }
        # Kuota/rate limit kemungkinan habis -> hentikan pengambilan.
        if status in (429, 402, 403):
            _save_json(cache_path, result)
            raise
    except httpx.HTTPError as exc:
        result = {
            "status": "error",
            "date": day.isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
            "articles": [],
        }

    _save_json(cache_path, result)
    return result


async def fetch_daily_news(
    coin_id: str, start: date, end: date, cache_dir: str, stop_event=None
) -> dict:
    """Fetch artikel per hari dengan cache; hasilkan coverage."""
    days = list(_daterange(start, end))
    results = {}
    quota_exhausted = False

    for i, day in enumerate(days):
        if stop_event is not None and stop_event.is_set():
            break
        cache_path = os.path.join(cache_dir, f"news_{coin_id}_{day.isoformat()}.json")
        try:
            results[day.isoformat()] = await _fetch_articles_for_day(
                coin_id, day, cache_path
            )
        except (httpx.HTTPStatusError, httpx.HTTPError):
            quota_exhausted = True
            break

        if i < len(days) - 1:
            await asyncio.sleep(GNEWS_DELAY_SECONDS)

    fetched = [d for d, r in results.items() if r.get("status") == "ok"]
    with_articles = [
        d for d in fetched if results[d].get("articles")
    ]

    return {
        "results": results,
        "coverage": {
            "days_requested": len(days),
            "days_fetched": len(fetched),
            "days_with_articles": len(with_articles),
            "quota_exhausted": quota_exhausted,
        },
    }


def analyze_daily_news(fetched: dict) -> dict:
    """FinBERT per artikel -> skor sentimen harian (0-100).

    Memakai analyze_news_sentiment + calculate_sentiment_score yang sama
    dengan endpoint /sentiment di production (model ProsusAI/finbert).
    """
    from app.services.sentiment_service import (
        analyze_news_sentiment,
        calculate_sentiment_score,
    )

    series = {}
    for day_iso, payload in fetched.items():
        if payload.get("status") != "ok":
            continue
        articles = payload.get("articles", [])
        if not articles:
            continue

        sentiment_articles = analyze_news_sentiment(articles)
        if not sentiment_articles:
            continue

        score = calculate_sentiment_score(sentiment_articles)
        series[day_iso] = {
            "score": score["sentiment_score"],
            "condition": score["condition"],
            "n_articles": len(sentiment_articles),
        }

    return series


async def get_daily_news_sentiment(
    coin_id: str,
    start: date,
    end: date,
    cache_dir: str,
    force: bool = False,
) -> dict:
    """Sentimen harian dari berita + FinBERT, dengan cache agregat.

    Returns
    -------
    {"series": {date_iso: {"score", "condition", "n_articles"}},
     "coverage": {...}}
    """
    os.makedirs(cache_dir, exist_ok=True)
    agg_path = os.path.join(
        cache_dir, f"sentiment_news_{coin_id}_{start.isoformat()}_{end.isoformat()}.json"
    )

    if not force:
        cached = _load_json(agg_path)
        if cached is not None:
            cov = cached.get("coverage") or {}
            complete = (
                not cov.get("quota_exhausted")
                and cov.get("days_fetched", 0) >= cov.get("days_requested", 0)
            )
            if complete:
                return cached
            # Aggregate parsial (kuota GNews habis) -> ambil ulang;
            # cache per hari membuatnya murah dan bisa dilanjut pada
            # run berikutnya (hari yang sudah ok tidak di-fetch lagi).

    fetched = await fetch_daily_news(coin_id, start, end, cache_dir)
    series = analyze_daily_news(fetched["results"])

    payload = {
        "coin_id": coin_id,
        "source": "gnews.io + ProsusAI/finbert",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "series": series,
        "coverage": fetched["coverage"],
    }
    _save_json(agg_path, payload)
    return payload
