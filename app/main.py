import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from app.services.cache_service import TTLCache
from app.services.crypto_service import (
    get_market_data,
    get_coin_detail,
    get_coin_history,
    get_coin_list,
    get_binance_live_prices,
    get_binance_24h_changes,
    resolve_coin_id
)

from app.services.technical_service import calculate_sma_ema
from app.services.scoring_service import calculate_technical_score, calculate_final_score
from app.services.recommendation_service import (
    generate_recommendation,
    build_execution_plan,
)
from app.services.news_service import get_crypto_news
from app.services.sentiment_service import analyze_news_sentiment, calculate_sentiment_score
from app.services.sentiment_history_service import get_fng_history
from app.services.telegram_service import (
    is_configured as tg_configured,
    send_telegram_alert,
    format_signal_alert,
    alert_scheduler_loop,
)
from app.services import portfolio_service


async def _alert_scan() -> tuple:
    """Snapshot data untuk satu siklus scheduler alert.

    Watchlist diambil tanpa query coins (default) + posisi portofolio
    live — dipakai `alert_scheduler_loop` sebagai callback.
    """
    data = await crypto_dashboard_watchlist(None)
    items = [c for c in data.get("coins", []) if "error" not in c]
    portfolio = await portfolio_service.list_positions()
    return items, portfolio.get("positions", [])


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Startup: jalankan background scheduler alert Telegram (30 menit
    # default, ALERT_INTERVAL_MINUTES di .env). Dormant tanpa token.
    task = asyncio.create_task(alert_scheduler_loop(_alert_scan))
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Recy API",
    description="Intelligent Crypto Market Insight API",
    version="0.1.0",
    lifespan=lifespan,
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


# ============ Tugas 3: Dashboard Watchlist Pribadi ============
# Koin pantauan default (Personal Trading Edition).
DEFAULT_WATCHLIST = ["bitcoin", "ethereum", "solana", "binancecoin", "ripple"]



def _requested_coins(coins: str = None) -> list:
    """Parse query `coins` (dipisah koma) -> daftar; default watchlist."""
    if coins and coins.strip():
        return [c.strip().lower() for c in coins.split(",") if c.strip()]
    return list(DEFAULT_WATCHLIST)


async def _resolve_coin_ids(requested: list) -> list:
    """Resolusi nama/simbol -> coin_id CoinGecko (dedupe, urutan utuh).

    Mis. "doge"/"Dogecoin" -> "dogecoin". get_coin_list di-cache 10 menit
    sehingga murah bahkan untuk polling cepat tiap 5 detik.
    """
    coin_ids = []
    for coin in requested:
        resolved = (await resolve_coin_id(coin)) or coin
        if resolved not in coin_ids:
            coin_ids.append(resolved)
    return coin_ids


async def _watchlist_meta() -> dict:
    """Map coin_id -> data /coins/list (di-cache 10 menit di crypto_service)."""
    try:
        coins = await get_coin_list()
        return {coin["id"]: coin for coin in coins}
    except Exception:
        # Gagal sekali pun tidak menjatuhkan seluruh watchlist.
        return {}


async def _watchlist_item(
    coin_id: str,
    meta: dict,
    live_price: float = None,
    change_24h_pct: float = None,
) -> dict:
    """Ringkas satu koin: harga, trend, rekomendasi, SL/TP.

    `live_price` (Binance public API, cache 5 detik) dipakai sebagai
    `current_price` sehingga harga di tabel & level SL/TP/trailing ikut
    bergerak real-time. Bila None (Binance gagal / koin tanpa pasangan),
    otomatis memakai harga harian CoinGecko (fallback tanpa error).
    """
    info = meta.get(coin_id, {})
    item = {
        "coin_id": coin_id,
        "name": info.get("name", coin_id),
        "symbol": (info.get("symbol") or coin_id).upper(),
        "change_24h_pct": change_24h_pct,
    }

    # Harga live Binance (bila tersedia) — fallback CoinGecko di bawah.
    price = float(live_price) if live_price else None
    price_source = "binance" if price is not None else "coingecko"

    try:
        history = await get_coin_history(coin_id, days=365)
        prices = history["prices"]
        volumes = history.get("total_volumes") or []

        technical_data = calculate_sma_ema(prices, volumes)
        latest_data = technical_data[-1]

        technical_score = calculate_technical_score(latest_data)

        # Harga live Binance menggantikan harga harian CoinGecko untuk
        # seluruh perhitungan eksekusi; ATR tetap dari data harian.
        if price is None:
            price = float(latest_data["price"])

        recommendation = generate_recommendation(
            technical_score["technical_score"],
            technical_score["condition"],
            trend_filter_ok=technical_score["trend_filter_ok"],
            coin_id=coin_id,
            current_price=price,
            atr_14=latest_data.get("atr_14"),
            price_source=price_source,
        )

        execution = recommendation["execution"]

        item.update({
            "price": execution["current_price"],
            "price_source": price_source,
            "trend": technical_score["condition"],  # BULLISH/NEUTRAL/BEARISH
            "recommendation": recommendation["recommendation"],  # BUY/HOLD/SELL
            "sl_price": execution["stop_loss_price"],
            "tp_price": execution["take_profit_price"],
            "trailing_stop_trigger": execution["trailing_stop_trigger"],
            "risk_reward_ratio": execution["risk_reward_ratio"],
            "suggested_allocation_pct": execution["suggested_allocation_pct"],
        })
    except Exception as exc:
        # Koin gagal (mis. 429/404) tidak menjatuhkan koin lain. Harga live
        # Binance tetap bisa tampil walau CoinGecko sedang error.
        item["error"] = f"{type(exc).__name__}: {exc}"
        if price is not None:
            item["price"] = price
            item["price_source"] = "binance"

    return item


@app.get("/api/crypto/dashboard/watchlist")
async def crypto_dashboard_watchlist(coins: str = None):
    """Ringkasan seluruh koin pantauan dalam SATU response JSON.

    Query opsional `coins` = daftar dipisah koma (contoh:
    ?coins=bitcoin,solana). Default: bitcoin, ethereum, solana,
    binancecoin, ripple.

    Data di-cache in-memory (history 5 menit, coin list 10 menit)
    agar panggilan berulang tidak kena HTTP 429 CoinGecko.
    """
    if coins and coins.strip():
        requested = [c.strip().lower() for c in coins.split(",") if c.strip()]
    else:
        requested = list(DEFAULT_WATCHLIST)

    # Resolusi nama/simbol -> coin_id CoinGecko (mis. "doge"/"Dogecoin"
    # -> "dogecoin"). get_coin_list di-cache 10 menit sehingga murah.
    coin_ids = await _resolve_coin_ids(requested)

    meta = await _watchlist_meta()

    # Harga live Binance (public API, cache 5 detik) + %24 jam — sekali
    # fetch untuk seluruh koin, diteruskan ke tiap item sehingga harga &
    # level SL/TP bergerak real-time. Gagal -> fallback CoinGecko per koin.
    live = await get_binance_live_prices(coin_ids)
    changes = await get_binance_24h_changes(coin_ids)

    # Fetch berurutan (bukan burst paralel): CoinGecko memberlakukan
    # limit jendela pendek — burst paralel memicu 401/429 pada koin
    # tertentu walau sudah ada retry. Saat semua koin sudah di-cache
    # (history 5 menit), endpoint tetap instan.
    items = []
    for coin_id in coin_ids:
        items.append(
            await _watchlist_item(
                coin_id,
                meta,
                live_price=live.get(coin_id),
                change_24h_pct=changes.get(coin_id),
            )
        )

    return {
        "count": len(items),
        "binance_live": bool(live),
        "coins": list(items),
    }


@app.get("/api/crypto/live-prices")
async def crypto_live_prices(coins: str = None):
    """Harga live Binance + level SL/TP terbaru — polling cepat UI (5 detik).

    Ringan di backend: history CoinGecko di-cache 5 menit dan harga
    Binance 5 detik, sehingga aman dipanggil berkali-kali tiap detik
    oleh dashboard agar harga & Stop-Loss bergerak real-time detik per
    detik. Selalu 200 — bila Binance gagal, item memakai harga CoinGecko
    (price_source="coingecko").
    """
    coin_ids = await _resolve_coin_ids(_requested_coins(coins))
    meta = await _watchlist_meta()

    live = await get_binance_live_prices(coin_ids)
    changes = await get_binance_24h_changes(coin_ids)

    items = []
    for coin_id in coin_ids:
        items.append(
            await _watchlist_item(
                coin_id,
                meta,
                live_price=live.get(coin_id),
                change_24h_pct=changes.get(coin_id),
            )
        )

    return {
        "count": len(items),
        "binance_live": bool(live),
        "coins": list(items),
    }

@app.get("/api/crypto/{coin_id}")
async def crypto_detail(coin_id: str):
    return await get_coin_detail(coin_id)

@app.get("/api/crypto/{coin_id}/history")
async def crypto_history(coin_id: str, days: int = 90):
    """Riwayat harga — `days` mendukung timeframe dashboard (7/30/90/365)."""
    return await get_coin_history(coin_id, days=days)

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

    # Harga live Binance (fallback CoinGecko) sebagai current_price —
    # level SL/TP/trailing dihitung ulang dari harga bursa yang bergerak.
    live = await get_binance_live_prices([coin_id])
    live_price = live.get(coin_id)
    changes = await get_binance_24h_changes([coin_id])

    price = float(live_price) if live_price else float(latest_data["price"])
    price_source = "binance" if live_price else "coingecko"

    recommendation = generate_recommendation(
        technical_score["technical_score"],
        technical_score["condition"],
        trend_filter_ok=technical_score["trend_filter_ok"],
        coin_id=coin_id,
        current_price=price,
        atr_14=latest_data.get("atr_14"),
        price_source=price_source,
    )

    return {
        "coin_id": coin_id,
        "price_source": price_source,
        "change_24h_pct": changes.get(coin_id),
        "technical": technical_score,
        "recommendation": recommendation,
        # Parameter eksekusi riil (angka praktis untuk trading pribadi):
        "execution": recommendation["execution"]
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

    # Tugas 1: parameter eksekusi riil juga muncul di endpoint analysis.
    # Phase 7: harga live Binance (fallback CoinGecko) agar SL/TP real-time.
    live = await get_binance_live_prices([resolved_coin_id])
    live_price = live.get(resolved_coin_id)
    price = float(live_price) if live_price else float(latest_data["price"])

    execution = build_execution_plan(
        coin_id=resolved_coin_id,
        current_price=price,
        atr_14=latest_data.get("atr_14"),
        recommendation=final["recommendation"],
        price_source="binance" if live_price else "coingecko",
    )

    return {
        "coin_id": resolved_coin_id,
        "technical": technical,
        "sentiment": sentiment,
        "final": final,
        "execution": execution,
        "articles": sentiment_articles
    }

@app.get("/api/coins")
async def coins_list():
    coins = await get_coin_list()

    return {
        "total_coins": len(coins),
        "coins": coins
    }


# ============ Dashboard: Fear & Greed Index (ticker pasar) ============
_fng_cache = TTLCache()
FNG_TTL = 15 * 60  # FNG update harian -> cache 15 menit cukup "live".


@app.get("/api/market/fng")
async def market_fng():
    """Fear & Greed Index terkini (alternative.me) — di-cache 15 menit."""
    cached, hit = _fng_cache.get("fng_latest")
    if hit:
        return cached

    try:
        series = await get_fng_history(days=30)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Fear & Greed Index tidak tersedia: {exc}",
        )

    latest_day = max(series)
    payload = {
        "date": latest_day,
        "score": series[latest_day]["score"],
        "classification": series[latest_day]["classification"],
        "source": "alternative.me",
    }
    _fng_cache.set("fng_latest", payload, FNG_TTL)
    return payload


# ============ Alerts: Telegram (opsional via .env) ============

@app.post("/api/alerts/telegram/test")
async def telegram_test():
    """Kirim pesan tes ke Telegram — graceful bila belum dikonfigurasi."""
    if not tg_configured():
        return {
            "sent": False,
            "configured": False,
            "detail": (
                "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID belum di-set di .env "
                "— alert dilewati tanpa error."
            ),
        }

    ok = await send_telegram_alert(
        "✅ <b>Recy Alert — Tes Berhasil</b>\n"
        "Notifikasi sinyal BUY &amp; trailing stop akan dikirim ke sini."
    )
    return {"sent": ok, "configured": True}


@app.post("/api/alerts/telegram/scan")
async def telegram_scan(coins: str = None):
    """Scan watchlist dan kirim alert Telegram untuk koin dengan sinyal BUY."""
    data = await crypto_dashboard_watchlist(coins)
    items = [c for c in data.get("coins", []) if "error" not in c]
    buys = [c for c in items if c.get("recommendation") == "BUY"]

    sent = 0
    if tg_configured():
        for item in buys:
            if await send_telegram_alert(format_signal_alert(item)):
                sent += 1

    return {
        "scanned": len(items),
        "buy_signals": len(buys),
        "sent": sent,
        "configured": tg_configured(),
    }


# ============ Portofolio: Jurnal Posisi Pribadi ============


class PositionIn(BaseModel):
    coin_id: str = Field(min_length=1, examples=["solana"])
    buy_price: float = Field(gt=0, examples=[150.5])
    amount: float = Field(gt=0, examples=[2.0])
    notes: str = ""


@app.post("/api/portfolio/positions", status_code=201)
async def portfolio_add_position(payload: PositionIn):
    """Catat posisi beli baru — coin_id di-resolve ("doge" -> dogecoin)."""
    resolved = await resolve_coin_id(payload.coin_id)
    if resolved is None:
        raise HTTPException(
            status_code=404,
            detail=f"Coin '{payload.coin_id}' tidak ditemukan di CoinGecko.",
        )
    try:
        position = portfolio_service.add_position(
            resolved, payload.buy_price, payload.amount, payload.notes
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"created": True, "position": position}


@app.get("/api/portfolio/positions")
async def portfolio_list_positions():
    """Semua posisi + live enrichment (PnL mengambang, status SL/trailing)."""
    return await portfolio_service.list_positions()


@app.delete("/api/portfolio/positions/{position_id}")
async def portfolio_delete_position(position_id: str):
    """Tutup/hapus satu posisi."""
    removed = portfolio_service.delete_position(position_id)
    if removed is None:
        raise HTTPException(status_code=404, detail="Posisi tidak ditemukan.")
    return {"deleted": True, "position": removed}


# ============ Dashboard (Crypto Terminal Edition) ============
STATIC_DIR = Path(__file__).resolve().parent / "static"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/dashboard")
async def serve_dashboard():
    return FileResponse(STATIC_DIR / "index.html")