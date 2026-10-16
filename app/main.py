import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from typing import Optional
from datetime import datetime, timezone

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
    get_binance_klines,
    resolve_coin_id
)

from app.services.technical_service import calculate_sma_ema
from app.services.scoring_service import (
    calculate_technical_score,
    calculate_final_score,
    SIGNAL_MODES,
    DEFAULT_SIGNAL_MODE,
    mode_thresholds,
)
from app.services.recommendation_service import (
    generate_recommendation,
    build_execution_plan,
    signal_from_score,
)
from app.services.news_service import get_crypto_news
from app.services.sentiment_service import analyze_news_sentiment, calculate_sentiment_score
from app.services.sentiment_history_service import get_fng_history
from app.services.backtest_service import build_technical_rows, signals_v1
from app.services.backtest_engine import simulate, compute_metrics
from app.services.telegram_service import (
    is_configured as tg_configured,
    send_telegram_alert,
    format_signal_alert,
    alert_scheduler_loop,
)
from app.services import portfolio_service
from app.services import price_alert_service


async def _check_price_alerts(items: list) -> list:
    """Evaluasi aturan alert harga custom memakai harga live `items`.

    Dipanggil dari endpoint watchlist/live-prices (UI poll tiap 5 detik)
    sehingga reaksi berlangsung dalam hitungan detik tanpa timer baru.
    Saat tersentuh: aturan dinonaktifkan (sekali tembak) + kirim Telegram
    (graceful bila belum dikonfigurasi). Return daftar terpicu utk UI.
    """
    prices = {}
    for c in items:
        if c.get("error") or c.get("price") is None:
            continue
        try:
            prices[c["coin_id"]] = float(c["price"])
        except (TypeError, ValueError):
            continue
    if not prices:
        return []

    triggered = price_alert_service.evaluate_alerts(prices)
    for a in triggered:
        arrow = "≥" if a["direction"] == "ABOVE" else "≤"
        # send_telegram_alert graceful — tanpa token cukup return False.
        await send_telegram_alert(
            "🚨 <b>Recy Price Alert</b>\n"
            f"{a['coin_id'].upper()} menyentuh batas {arrow} "
            f"${a['target_price']:,.2f}\n"
            f"Harga live: ${a['trigger_price']:,.2f}"
        )
    return triggered


async def _check_indicator_alerts(coin_ids: list) -> list:
    """Nilai RSI14/ADX terkini (history CoinGecko cache 5 mnt) -> evaluasi
    aturan indikator + kirim Telegram bila terpicu."""
    values = {}
    for cid in dict.fromkeys(coin_ids):  # dedupe, urutan terjaga
        try:
            history = await get_coin_history(cid, days=365)
            latest = calculate_sma_ema(
                history["prices"], history.get("total_volumes") or []
            )[-1]
            values[cid] = {
                "RSI14": latest.get("rsi_14"),
                "ADX": latest.get("adx_14"),
            }
        except Exception:  # koin gagal -> dilewati, aturan lain tetap jalan
            continue

    triggered = price_alert_service.evaluate_indicator_alerts(values)
    for a in triggered:
        arrow = "≥" if a["direction"] == "ABOVE" else "≤"
        await send_telegram_alert(
            "📉 <b>Recy Indicator Alert</b>\n"
            f"{a['coin_id'].upper()} {a['indicator']} {arrow} {a['target']:g}\n"
            f"Nilai terkini: {a['trigger_value']:g}"
        )
    return triggered


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
    # default, ALERT_INTERVAL_MINUTES di .env) + Daily Digest (sekali
    # sehari, DIGEST_HOUR di .env). Dormant tanpa token.
    task = asyncio.create_task(alert_scheduler_loop(_alert_scan))
    digest_task = asyncio.create_task(_digest_scheduler_loop())
    try:
        yield
    finally:
        task.cancel()
        digest_task.cancel()
        for t in (task, digest_task):
            try:
                await t
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


# ============================================================================
# Timeframe sinyal dinamis (Phase 11): indikator teknikal dihitung dari
# candle Binance (get_binance_klines) sesuai timeframe yang dipilih UI.
# ============================================================================
SIGNAL_TIMEFRAMES = ("15m", "1h", "4h", "1D", "1W")

# tf -> (interval klines Binance, jumlah bar). Bar cukup utk warm-up
# indikator (SMA/EMA 200 butuh 200 bar).
_TF_KLINES = {
    "15m": ("15m", 600),   # 600 x 15m ≈ 6.2 hari
    "1h": ("1h", 500),
    "4h": ("4h", 400),
    "1D": ("1d", 400),
    "1W": None,            # mingguan -> harian CoinGecko 365 hari (≈52 minggu)
}


def _normalize_tf(tf: str) -> str:
    tf = (tf or "1D").strip()
    return tf if tf in SIGNAL_TIMEFRAMES else "1D"


def _normalize_mode(mode: str) -> str:
    mode = (mode or "").strip().lower()
    return mode if mode in SIGNAL_MODES else DEFAULT_SIGNAL_MODE


async def _signal_series(coin_id: str, tf: str = "1D", days: int = 365):
    """(prices, volumes, source) untuk kalkulasi indikator pada timeframe `tf`.

    - tf intraday/harian (15m/1h/4h/1D): candle OHLCV Binance via
      get_binance_klines (cache 30 dtk / 5 mnt, tanpa API key).
    - koin TANPA pasangan USDT di Binance / klines gagal / tf 1W:
      fallback mulus ke riwayat harian CoinGecko (data historis) — tanpa
      error, baris watchlist tetap utuh (requirement fallback).

    Return (None, None, None) bila kedua sumber tidak tersedia.
    """
    conf = _TF_KLINES.get(tf)
    if conf:
        payload = await get_binance_klines(
            coin_id, interval=conf[0], limit=conf[1]
        )
        if payload and payload.get("bars"):
            bars = payload["bars"]
            prices = [[b["time"] * 1000, b["close"]] for b in bars]
            volumes = [[b["time"] * 1000, b["volume"]] for b in bars]
            return prices, volumes, "binance_klines"

    history = await get_coin_history(coin_id, days=days)
    if history is None or not history.get("prices"):
        return None, None, None
    return (
        history["prices"],
        history.get("total_volumes") or [],
        "coingecko",
    )


async def _watchlist_item(
    coin_id: str,
    meta: dict,
    live_price: float = None,
    change_24h_pct: float = None,
    tf: str = "1D",
    mode: str = "swing",
) -> dict:
    """Ringkas satu koin: harga, trend, rekomendasi, SL/TP.

    `live_price` (Binance public API, cache 5 detik) dipakai sebagai
    `current_price` sehingga harga di tabel & level SL/TP/trailing ikut
    bergerak real-time. Bila None (Binance gagal / koin tanpa pasangan),
    otomatis memakai harga harian CoinGecko (fallback tanpa error).

    `tf`  : timeframe sinyal (15m/1h/4h/1D/1W) — indikator teknikal
            dihitung dari candle Binance sesuai timeframe (fallback
            CoinGecko bila koin tanpa pasangan / klines gagal).
    `mode`: trading style (scalp/swing) — ambang BUY/SELL + filter trend.
    """
    info = meta.get(coin_id, {})
    item = {
        "coin_id": coin_id,
        "name": info.get("name", coin_id),
        "symbol": (info.get("symbol") or coin_id).upper(),
        "change_24h_pct": change_24h_pct,
        "tf": tf,
        "mode": mode,
    }

    # Harga live Binance (bila tersedia) — fallback CoinGecko di bawah.
    price = float(live_price) if live_price else None
    price_source = "binance" if price is not None else "coingecko"

    # Koin tidak dikenal CoinGecko (typo saat add) -> penanda permanen
    # `not_found` — frontend HANYA menghapus koin kustom berdasarkan ini
    # (bukan error sementara), sesuai aturan persistensi watchlist.
    if meta and coin_id not in meta:
        item["not_found"] = True
        item["error"] = f"Koin '{coin_id}' tidak ditemukan di CoinGecko."
        if price is not None:
            item["price"] = price
            item["price_source"] = "binance"
        return item

    try:
        prices, volumes, data_source = await _signal_series(coin_id, tf)
        if prices is None:
            raise RuntimeError(
                "Data harga tidak tersedia (rate-limit CoinGecko / offline)"
            )

        technical_data = calculate_sma_ema(prices, volumes)
        if not technical_data:
            raise RuntimeError("Data indikator kosong (jendela terlalu pendek)")
        latest_data = technical_data[-1]
        prev_data = technical_data[-2] if len(technical_data) > 1 else None

        technical_score = calculate_technical_score(
            latest_data, mode=mode, prev=prev_data
        )

        # Harga live Binance menggantikan harga harian CoinGecko untuk
        # seluruh perhitungan eksekusi; ATR tetap dari data timeframe aktif.
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
            mode=mode,
        )

        execution = recommendation["execution"]

        item.update({
            "price": execution["current_price"],
            "price_source": price_source,
            "trend": technical_score["condition"],  # BULLISH/NEUTRAL/BEARISH
            # ADX utk filter scanner "Trending" di UI (tanpa panggilan API baru).
            "adx_14": technical_score.get("adx_14"),
            "recommendation": recommendation["recommendation"],  # BUY/HOLD/SELL
            # Signal Strength Gauge (Phase 11): kekuatan + label sinyal.
            "signal": {
                "strength": recommendation["signal_strength"],
                "label": recommendation["signal_label"],
                "recommendation": recommendation["recommendation"],
                "buy_threshold": recommendation["buy_threshold"],
                "sell_threshold": recommendation["sell_threshold"],
                "mode": mode,
                "tf": tf,
                "mode_label": SIGNAL_MODES.get(mode, {}).get("label", mode),
            },
            # Sumber data indikator timeframe aktif (binance klines / coingecko).
            "signal_source": data_source,
            "sl_price": execution["stop_loss_price"],
            "tp_price": execution["take_profit_price"],
            "trailing_stop_trigger": execution["trailing_stop_trigger"],
            "risk_reward_ratio": execution["risk_reward_ratio"],
            "suggested_allocation_pct": execution["suggested_allocation_pct"],
        })
    except Exception as exc:
        # Koin gagal (mis. 429/404) tidak menjatuhkan koin lain. Harga live
        # Binance tetap bisa tampil walau CoinGecko sedang error — frontend
        # menampilkan "Data Terbatas / Offline" + tombol retry (koin TETAP
        # di watchlist, tidak dihapus dari localStorage).
        item["error"] = f"{type(exc).__name__}: {exc}"
        if price is not None:
            item["price"] = price
            item["price_source"] = "binance"

    return item


@app.get("/api/crypto/dashboard/watchlist")
async def crypto_dashboard_watchlist(
    coins: str = None, tf: str = "1D", mode: str = "swing"
):
    """Ringkasan seluruh koin pantauan dalam SATU response JSON.

    Query opsional `coins` = daftar dipisah koma (contoh:
    ?coins=bitcoin,solana). Default: bitcoin, ethereum, solana,
    binancecoin, ripple.

    Query opsional Phase 11:
    - `tf`   : timeframe sinyal (15m/1h/4h/1D/1W) — indikator dihitung
      dari candle Binance sesuai timeframe (fallback CoinGecko).
    - `mode` : trading style — "scalp" (BUY>=60/SELL<40) atau
      "swing" (BUY>=68/SELL<32, standar).

    Data di-cache in-memory (history 5 menit, coin list 10 menit)
    agar panggilan berulang tidak kena HTTP 429 CoinGecko.
    """
    tf = _normalize_tf(tf)
    mode = _normalize_mode(mode)

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
                tf=tf,
                mode=mode,
            )
        )

    # Evaluasi alert harga custom (Phase 9) — reaksi detik, notif UI + TG.
    triggered_alerts = await _check_price_alerts(items)

    return {
        "count": len(items),
        "tf": tf,
        "mode": mode,
        "binance_live": bool(live),
        "alerts_triggered": triggered_alerts,
        "coins": list(items),
    }


@app.get("/api/crypto/live-prices")
async def crypto_live_prices(
    coins: str = None, tf: str = "1D", mode: str = "swing"
):
    """Harga live Binance + level SL/TP terbaru — polling cepat UI (5 detik).

    Ringan di backend: history CoinGecko di-cache 5 menit dan harga
    Binance 5 detik, sehingga aman dipanggil berkali-kali tiap detik
    oleh dashboard agar harga & Stop-Loss bergerak real-time detik per
    detik. Selalu 200 — bila Binance gagal, item memakai harga CoinGecko
    (price_source="coingecko").

    `tf` & `mode` mengikuti pilihan sinyal UI agar rekomendasi/SL/TP di
    polling ini konsisten dengan watchlist (lihat endpoint watchlist).
    """
    tf = _normalize_tf(tf)
    mode = _normalize_mode(mode)

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
                tf=tf,
                mode=mode,
            )
        )

    # Evaluasi alert harga custom (Phase 9) — reaksi detik, notif UI + TG.
    triggered_alerts = await _check_price_alerts(items)

    return {
        "count": len(items),
        "tf": tf,
        "mode": mode,
        "binance_live": bool(live),
        "alerts_triggered": triggered_alerts,
        "coins": list(items),
    }

@app.get("/api/crypto/{coin_id}")
async def crypto_detail(coin_id: str):
    return await get_coin_detail(coin_id)

@app.get("/api/crypto/{coin_id}/history")
async def crypto_history(coin_id: str, days: int = 90):
    """Riwayat harga — `days` mendukung timeframe dashboard (7/30/90/365)."""
    return await get_coin_history(coin_id, days=days)


@app.get("/api/crypto/{coin_id}/klines")
async def crypto_klines(coin_id: str, interval: str = "1h", limit: int = 200):
    """Candle OHLCV Binance (15m/30m/1h/4h/1d) — chart candlestick live.

    Publik, tanpa API key. 404 bila koin tanpa pasangan USDT atau
    interval di luar whitelist (frontend fallback ke riwayat CoinGecko).
    """
    payload = await get_binance_klines(
        coin_id, interval=interval, limit=limit
    )
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Klines '{coin_id}' interval '{interval}' tidak tersedia "
                "(koin tanpa pasangan Binance / interval tidak valid)."
            ),
        )
    return payload

@app.get("/api/crypto/{coin_id}/technical")
async def crypto_technical(coin_id: str, days: int = 365):
    history = await get_coin_history(coin_id, days=days)
    if history is None:
        raise HTTPException(status_code=503, detail="Data harga sementara tidak tersedia (rate-limit CoinGecko).")

    prices = history["prices"]
    volumes = history.get("total_volumes") or []

    return calculate_sma_ema(prices, volumes)

async def _detail_series(coin_id: str, tf: str, days: int):
    """(technical_data, prev_data, data_source) utk endpoint detail.

    Sama dengan _signal_series, dengan fallback window lebih kecil (90 hari)
    saat CoinGecko 429 — request ringan lebih mungkin lolos daripada 500.
    """
    tf = _normalize_tf(tf)
    prices, volumes, data_source = await _signal_series(coin_id, tf, days=days)
    if prices is None:
        # CoinGecko 429 (kuota habis) -> coba window lebih kecil; request
        # ringan ini lebih mungkin lolos dan tetap beri sinyal daripada 500.
        history = await get_coin_history(coin_id, days=90)
        if history is not None and history.get("prices"):
            prices = history["prices"]
            volumes = history.get("total_volumes") or []
            data_source = "coingecko"
    if prices is None:
        raise HTTPException(
            status_code=503,
            detail="Data harga sementara tidak tersedia (rate-limit CoinGecko / Binance).",
        )

    technical_data = calculate_sma_ema(prices, volumes)
    if not technical_data:
        raise HTTPException(
            status_code=503,
            detail="Data indikator kosong (jendela timeframe terlalu pendek).",
        )
    latest_data = technical_data[-1]
    prev_data = technical_data[-2] if len(technical_data) > 1 else None
    return latest_data, prev_data, data_source


@app.get("/api/crypto/{coin_id}/technical/score")
async def crypto_technical_score(
    coin_id: str, days: int = 365, tf: str = "1D", mode: str = "swing"
):
    """Skor teknikal + Signal Strength Gauge pada timeframe (`tf`) aktif.

    `mode` (scalp/swing) menentukan ambang BUY/SELL + filter trend;
    response menyertakan `signal` (strength/label/threshold) utk gauge UI.
    """
    mode = _normalize_mode(mode)
    latest_data, prev_data, data_source = await _detail_series(coin_id, tf, days)

    score = calculate_technical_score(latest_data, mode=mode, prev=prev_data)
    signal = signal_from_score(
        score["technical_score"],
        score["condition"],
        trend_filter_ok=score["trend_filter_ok"],
        mode=mode,
    )
    # Konteks UI (gauge): timeframe & label mode aktif.
    signal["tf"] = _normalize_tf(tf)
    signal["mode_label"] = SIGNAL_MODES.get(mode, {}).get("label", mode)

    return {
        "coin_id": coin_id,
        "tf": _normalize_tf(tf),
        "mode": mode,
        "data_source": data_source,
        "latest_data": latest_data,
        "score": score,
        "signal": signal,
    }

@app.get("/api/crypto/{coin_id}/recommendation")
async def crypto_recommendation(
    coin_id: str, days: int = 365, tf: str = "1D", mode: str = "swing"
):
    """Rekomendasi + eksekusi pada timeframe (`tf`) & trading style (`mode`)."""
    mode = _normalize_mode(mode)
    tf = _normalize_tf(tf)

    latest_data, prev_data, data_source = await _detail_series(coin_id, tf, days)

    technical_score = calculate_technical_score(
        latest_data, mode=mode, prev=prev_data
    )

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
        mode=mode,
    )

    return {
        "coin_id": coin_id,
        "tf": tf,
        "mode": mode,
        "data_source": data_source,
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
async def crypto_analysis(
    coin_id: str, days: int = 365, tf: str = "1D", mode: str = "swing"
):
    """Eksekusi + sentimen berita pada timeframe (`tf`) & mode (`mode`)."""

    resolved_coin_id = await resolve_coin_id(coin_id)

    if resolved_coin_id is None:
        raise HTTPException(
            status_code=404,
            detail=f"Coin '{coin_id}' tidak ditemukan di CoinGecko."
        )

    mode = _normalize_mode(mode)
    latest_data, prev_data, data_source = await _detail_series(
        resolved_coin_id, tf, days
    )

    technical = calculate_technical_score(latest_data, mode=mode, prev=prev_data)

    news = await get_crypto_news(resolved_coin_id)

    articles = news["articles"]

    sentiment_articles = analyze_news_sentiment(
        articles
    )

    sentiment = calculate_sentiment_score(
        sentiment_articles
    )

    # Threshold final score mengikuti trading style aktif (scalp 60/40,
    # swing 68/32) agar konsisten dengan sinyal watchlist/gauge.
    buy_threshold, sell_threshold = mode_thresholds(mode)
    final = calculate_final_score(
        technical_score=technical["technical_score"],
        sentiment_score=sentiment["sentiment_score"],
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
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
        "tf": _normalize_tf(tf),
        "mode": mode,
        "data_source": data_source,
        "technical": technical,
        "sentiment": sentiment,
        "final": final,
        "execution": execution,
        "articles": sentiment_articles
    }

@app.get("/api/coins/resolve")
async def coin_resolve(q: str):
    """Resolusi satu query (id/nama/simbol/alias) -> coin_id CoinGecko.

    Dipakai tombol "Tambah" di dashboard: koin kustom disimpan dengan
    coin_id FINAL (mis. "doge"/"Dogecoin" -> "dogecoin") sehingga tombol
    hapus (x) selalu tampil dan koin tidak salah terdeteksi "tidak
    ditemukan" hanya karena beda bentuk nama. 404 bila tidak dikenal.
    """
    resolved = await resolve_coin_id(q)
    if resolved is None:
        raise HTTPException(
            status_code=404,
            detail=f"Koin '{q}' tidak ditemukan di CoinGecko.",
        )
    info = {}
    try:
        coins = await get_coin_list()
        info = next((c for c in coins if c["id"] == resolved), {})
    except Exception:  # noqa: BLE001 — meta bersifat pelengkap
        pass
    return {
        "query": q,
        "coin_id": resolved,
        "name": info.get("name"),
        "symbol": (info.get("symbol") or "").upper(),
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


# ============ Phase 9: Backtest On-Demand (Uji Strategi) ============
_bt_cache = TTLCache()
BT_TTL = 10 * 60  # sinyal teknikal berubah pelan -> cache 10 menit.


def _utc_date_ms(timestamp_ms) -> str:
    return datetime.fromtimestamp(
        timestamp_ms / 1000, tz=timezone.utc
    ).date().isoformat()


async def _backtest_report(coin_id: str, days: int = 365) -> dict:
    """Backtest cepat sinyal teknikal V1 (threshold baseline 70/30)
    + ATR SL 1.5x + ATR Trailing Stop — memakai mesin backtest yang
    sama dengan 29 unit test & walk-forward (tanpa lookahead).

    Fee 0.1% per sisi (taker Binance). History CoinGecko cache 5 menit
    sehingga aman dipanggil berulang dari UI.
    """
    days = max(90, min(int(days), 730))
    key = ("bt", coin_id, days)
    cached, hit = _bt_cache.get(key)
    if hit:
        return cached

    history = await get_coin_history(coin_id, days=days)
    if history is None:
        raise HTTPException(
            status_code=503,
            detail="Data harga sementara tidak tersedia (rate-limit CoinGecko).",
        )
    rows = build_technical_rows(
        history["prices"], history.get("total_volumes") or []
    )
    signals = signals_v1(rows)  # BUY >= 70 / SELL < 30 (baseline)

    start_index = next(
        (
            i for i, s in enumerate(signals)
            if s and s.get("signal") is not None
        ),
        None,
    )
    if start_index is None:
        raise ValueError(
            "Tidak ada sinyal pada rentang ini — coba rentang lebih panjang."
        )

    prices = [s["price"] for s in signals]
    atr = [s.get("atr") for s in signals]

    sim = simulate(
        prices,
        signals,
        fee_rate=0.001,
        atr=atr,
        use_atr_stop_loss=True,
        atr_multiplier=1.5,   # sama dengan SL_ATR_MULT plan dashboard
        use_trailing_stop=True,
    )
    metrics = compute_metrics(
        prices, signals, sim, start_index=start_index
    )

    report = {
        "coin_id": coin_id,
        "days": days,
        "start_date": _utc_date_ms(rows[start_index]["timestamp"]),
        "end_date": _utc_date_ms(rows[-1]["timestamp"]),
        "strategy": (
            "V1 teknikal (BUY≥70 / SELL<30) + ATR SL 1.5× "
            "+ ATR Trailing Stop"
        ),
        "fee_pct_per_side": 0.1,
        "metrics": metrics,
    }
    _bt_cache.set(key, report, BT_TTL)
    return report


@app.get("/api/backtest/{coin_id}")
async def backtest_coin(coin_id: str, days: int = 365):
    """Uji strategi satu koin: win rate, return vs buy&hold, max DD,
    Sharpe, jumlah trade & exit SL/TP/trailing."""
    resolved = await resolve_coin_id(coin_id)
    if resolved is None:
        raise HTTPException(
            status_code=404,
            detail=f"Coin '{coin_id}' tidak ditemukan di CoinGecko.",
        )
    try:
        return await _backtest_report(resolved, days)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


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


# ============ Phase 9: Alert Harga Custom (Price Alerts) ============


class PriceAlertIn(BaseModel):
    coin_id: str = Field(min_length=1, examples=["bitcoin"])
    direction: str = Field(default="ABOVE", examples=["ABOVE"])
    target_price: float = Field(gt=0, examples=[90000.0])


@app.get("/api/alerts/price")
async def price_alert_list():
    """Daftar aturan alert harga (aktif + riwayat terpicu terbaru)."""
    return price_alert_service.list_alerts()


@app.post("/api/alerts/price", status_code=201)
async def price_alert_add(payload: PriceAlertIn):
    """Tambah aturan: beritahu saat harga live menyentuh target.

    Evaluasi berjalan otomatis di endpoint live-prices (poll 5 detik);
    sekali tembak — aturan nonaktif setelah terpicu.
    """
    resolved = await resolve_coin_id(payload.coin_id)
    if resolved is None:
        raise HTTPException(
            status_code=404,
            detail=f"Coin '{payload.coin_id}' tidak ditemukan di CoinGecko.",
        )
    try:
        alert = price_alert_service.add_alert(
            resolved, payload.direction, payload.target_price
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"created": True, "alert": alert}


@app.delete("/api/alerts/price/{alert_id}")
async def price_alert_delete(alert_id: str):
    """Hapus satu aturan alert (harga/indikator, aktif/terpicu)."""
    removed = price_alert_service.delete_alert(alert_id)
    if removed is None:
        raise HTTPException(status_code=404, detail="Alert tidak ditemukan.")
    return {"deleted": True, "alert": removed}


class IndicatorAlertIn(BaseModel):
    coin_id: str = Field(min_length=1, examples=["solana"])
    indicator: str = Field(default="RSI14", examples=["RSI14"])
    direction: str = Field(default="BELOW", examples=["BELOW"])
    target: float = Field(gt=0, examples=[30.0])


@app.post("/api/alerts/indicator", status_code=201)
async def indicator_alert_add(payload: IndicatorAlertIn):
    """Tambah aturan alert indikator (RSI14 / ADX) — sekali tembak.

    Dievaluasi di endpoint check (poll 10 dtk) dari history CoinGecko
    yang sudah di-cache 5 menit — tanpa request API tambahan berarti.
    """
    resolved = await resolve_coin_id(payload.coin_id)
    if resolved is None:
        raise HTTPException(
            status_code=404,
            detail=f"Coin '{payload.coin_id}' tidak ditemukan di CoinGecko.",
        )
    try:
        alert = price_alert_service.add_indicator_alert(
            resolved, payload.indicator, payload.direction, payload.target
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"created": True, "alert": alert}


@app.get("/api/alerts/price/check")
async def price_alert_check(coins: str = None):
    """Cek alert memakai harga live Binance — RINGAN (batch cache 5 dtk).

    Dipoll UI tiap 10 detik secara independen sehingga aturan tetap
    bereaksi detik walau WebSocket menahan polling harga. Koin pada
    aturan aktif di luar watchlist ikut diperiksa.
    """
    coin_ids = await _resolve_coin_ids(_requested_coins(coins))
    alerts_snapshot = price_alert_service.list_alerts()
    for a in alerts_snapshot["active"] + alerts_snapshot["indicator_active"]:
        if a["coin_id"] not in coin_ids:
            coin_ids.append(a["coin_id"])

    live = await get_binance_live_prices(coin_ids)
    items = [
        {"coin_id": cid, "price": live.get(cid)}
        for cid in coin_ids
    ]
    triggered = await _check_price_alerts(items)

    # (Phase 10) Alert indikator (RSI14/ADX) — history cache 5 menit.
    ind_triggered = await _check_indicator_alerts(
        [a["coin_id"] for a in alerts_snapshot["indicator_active"]]
    )

    return {
        "count": len(triggered) + len(ind_triggered),
        "alerts_triggered": triggered,
        "indicator_alerts_triggered": ind_triggered,
    }


# ============ Phase 10: Daily Digest (ringkasan pagi via Telegram) ============
# Jam lokal pengiriman (0-23) — atur DIGEST_HOUR di .env (default 07:00).
DIGEST_HOUR = int(os.getenv("DIGEST_HOUR", "7") or 7)


async def build_daily_digest() -> str:
    """Susun pesan ringkasan personal: pasar watchlist, portofolio,
    realized PnL, Fear & Greed, dan alert terpicu. Tanpa network tambahan
    (semua dari pipeline yang sudah di-cache)."""
    data = await crypto_dashboard_watchlist(None)
    items = [c for c in data.get("coins", []) if "error" not in c]
    portfolio = await portfolio_service.list_positions()
    closed = await portfolio_service.closed_summary()
    alerts = price_alert_service.list_alerts()

    fng_s = "—"
    try:
        series = await get_fng_history(days=2)
        day = max(series)
        fng_s = (
            f"{series[day]['score']:.0f} — {series[day]['classification']}"
        )
    except Exception:  # FNG gagal -> digest tetap terkirim
        pass

    lines = []
    for c in items[:5]:
        ch = c.get("change_24h_pct")
        ch_s = f" ({ch:+.2f}%)" if ch is not None else ""
        price = c.get("price")
        price_s = f"${price:,.2f}" if price is not None else "—"
        lines.append(
            f"• {c.get('symbol', '?')} {price_s}{ch_s} — "
            f"{c.get('recommendation', '—')}"
        )
    market_s = "\n".join(lines) or "• (data tidak tersedia)"

    totals = portfolio.get("totals", {})
    val = totals.get("total_value_usd")
    pnl = totals.get("total_pnl_usd")
    pf_line = f"• Posisi aktif: {portfolio.get('count', 0)}"
    if val is not None:
        pf_line += f" | Nilai ${val:,.2f}"
    if pnl is not None:
        pf_line += f" | Floating {pnl:+,.2f} USD"
    realized_line = (
        f"• Realized {closed['total_realized_pnl_usd']:+,.2f} USD | "
        f"Win rate {closed['win_rate_pct']:.0f}% "
        f"({closed['win_count']}W/{closed['loss_count']}L)"
    )
    n_triggered = len(alerts["triggered"]) + len(alerts["indicator_triggered"])

    today = datetime.now(timezone.utc).strftime("%d %b %Y")
    return (
        f"📅 <b>Recy Daily Digest — {today}</b>\n\n"
        f"📊 <b>Pasar</b>\n{market_s}\n"
        f"• Fear &amp; Greed: {fng_s}\n\n"
        f"💼 <b>Portofolio</b>\n{pf_line}\n{realized_line}\n\n"
        f"🔔 Alert terpicu (riwayat terbaru): {n_triggered}\n\n"
        "<i>Semua angka informatif — bukan nasihat investasi.</i>"
    )


async def _digest_scheduler_loop() -> None:
    """Kirim digest sekali sehari saat jam lokal >= DIGEST_HOUR.

    Dicek tiap 5 menit; sekali dianggap terkirim untuk hari itu (baik
    berhasil maupun Telegram belum dikonfigurasi) agar tidak spam.
    """
    last_sent = None
    while True:
        try:
            now = datetime.now().astimezone()
            today = now.date().isoformat()
            if now.hour >= DIGEST_HOUR and last_sent != today:
                last_sent = today
                if tg_configured():
                    await send_telegram_alert(await build_daily_digest())
                    print(f"[Digest] terkirim {now.isoformat()}", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"[Digest] gagal: {type(exc).__name__}: {exc}", flush=True)
        await asyncio.sleep(300)


@app.post("/api/alerts/digest/test")
async def digest_test():
    """Kirim (atau preview bila Telegram belum di-set) digest sekarang."""
    message = await build_daily_digest()
    sent = False
    if tg_configured():
        sent = await send_telegram_alert(message)
    return {"sent": sent, "configured": tg_configured(), "preview": message}


# ============ Phase 10: Backup & Restore Jurnal ============

@app.get("/api/portfolio/backup")
async def portfolio_backup():
    """Snapshot jurnal (posisi + riwayat trade + semua alert) utk unduhan."""
    return {
        "app": "recy",
        "type": "recy-journal-backup",
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "portfolio": portfolio_service.backup_payload(),
        "alerts": price_alert_service.backup_payload(),
    }


class RestoreIn(BaseModel):
    mode: str = Field(default="merge", examples=["merge"])
    portfolio: Optional[dict] = None
    alerts: Optional[dict] = None


@app.post("/api/portfolio/restore")
async def portfolio_restore(payload: RestoreIn):
    """Pulihkan jurnal dari file backup — `merge` (union by id) / `replace`."""
    if payload.mode not in ("merge", "replace"):
        raise HTTPException(
            status_code=422, detail="mode harus 'merge' atau 'replace'."
        )
    result = {"portfolio": None, "alerts": None}
    try:
        if payload.portfolio is not None:
            result["portfolio"] = portfolio_service.restore_payload(
                payload.portfolio, payload.mode
            )
        if payload.alerts is not None:
            result["alerts"] = price_alert_service.restore_payload(
                payload.alerts, payload.mode
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"restored": True, **result}


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
    """Hapus satu posisi aktif tanpa mencatat realized PnL."""
    removed = portfolio_service.delete_position(position_id)
    if removed is None:
        raise HTTPException(status_code=404, detail="Posisi tidak ditemukan.")
    return {"deleted": True, "position": removed}


# ============ Phase 8: Closed Trades Tracker (Jurnal Trade Selesai) ============


class PositionCloseIn(BaseModel):
    # None -> harga live Binance (fallback CoinGecko) saat posisi ditutup.
    exit_price: Optional[float] = Field(default=None, gt=0, examples=[85000.0])
    exit_reason: str = Field(default="MANUAL", examples=["TP"])


@app.post("/api/portfolio/positions/{position_id}/close")
async def portfolio_close_position(
    position_id: str,
    payload: Optional[PositionCloseIn] = None,
):
    """Tutup posisi -> pindah ke jurnal trade selesai (realized PnL)."""
    body = payload or PositionCloseIn()
    try:
        closed = await portfolio_service.close_position(
            position_id,
            exit_price=body.exit_price,
            exit_reason=body.exit_reason,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"closed": True, "trade": closed}


@app.get("/api/portfolio/summary")
async def portfolio_summary():
    """Metrik trade tertutup: realized PnL, win rate, jumlah trade + riwayat."""
    return await portfolio_service.closed_summary()


# ============ Dashboard (Crypto Terminal Edition) ============
STATIC_DIR = Path(__file__).resolve().parent / "static"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/dashboard")
async def serve_dashboard():
    # Tanpa header cache: browser SELALU memvalidasi index.html terbaru
    # (perubahan UI langsung terlihat setelah refresh tanpa hard-refresh).
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )