import pandas as pd

from app.services.technical_service import calculate_sma_ema
from app.services.scoring_service import calculate_technical_score, calculate_final_score
from app.services.recommendation_service import generate_recommendation
from app.services.backtest_engine import BUY, HOLD, SELL


# Preset threshold rekomendasi (buy, sell) untuk backtest.
# "baseline" = 70/30 sesuai planning doc; lainnya lebih responsif.
THRESHOLD_PRESETS = {
    "baseline": (70, 30),
    "sensitif": (60, 40),
    "moderasi": (65, 35),
    "aggressive": (55, 45),
}


def run_technical_backtest(prices: list) -> list:
    """
    Menjalankan backtesting berdasarkan technical score.

    prices:
        Data harga dari CoinGecko dalam format:
        [
            [timestamp, price],
            [timestamp, price],
            ...
        ]
    """

    # 1. Hitung indikator teknikal
    technical_data = calculate_sma_ema(prices)

    # 2. Ubah hasil menjadi DataFrame
    df = pd.DataFrame(technical_data)

    # 3. Pastikan data diurutkan berdasarkan waktu
    df = df.sort_values("timestamp").reset_index(drop=True)

    results = []

    # 4. Gunakan harga hari berikutnya sebagai actual result
    for i in range(len(df) - 1):

        current_data = df.iloc[i]
        next_data = df.iloc[i + 1]

        # 5. Hitung technical score
        technical_score = calculate_technical_score(
            current_data.to_dict()
        )

        # 6. Tentukan rekomendasi
        recommendation = generate_recommendation(
            technical_score["technical_score"],
            technical_score["condition"],
            trend_filter_ok=technical_score["trend_filter_ok"]
        )

        current_price = current_data["price"]
        next_price = next_data["price"]

        # 7. Hitung return hari berikutnya
        next_day_return = (
            (next_price - current_price)
            / current_price
        ) * 100

        # 8. Simpan hasil
        results.append({
            "timestamp": current_data["timestamp"],
            "price": current_price,

            "technical_score": technical_score[
                "technical_score"
            ],

            "condition": technical_score[
                "condition"
            ],

            "recommendation": recommendation[
                "recommendation"
            ],

            "next_price": next_price,

            "next_day_return": round(
                next_day_return,
                2
            )
        })

    return results


# =====================================================================
# Helper tanggal (semua timestamp CoinGecko = 00:00 UTC)
# =====================================================================

def _utc_date(timestamp_ms) -> str:
    return pd.to_datetime(timestamp_ms, unit="ms", utc=True).date().isoformat()


def build_technical_rows(prices: list, volumes: list = None) -> list:
    """Hitung indikator teknikal dan urutkan berdasarkan timestamp.

    `volumes` (opsional): `total_volumes` CoinGecko — parallel array
    dengan `prices`; bila None kolom volume diisi None (skor netral).
    """
    rows = calculate_sma_ema(prices, volumes)
    rows = sorted(rows, key=lambda r: r["timestamp"])
    return rows


def sentiment_as_of(sentiment_by_date: dict, date_iso: str, lag_days: int = 1):
    """Ambil sentimen terbaru yang benar-benar sudah tersedia di `date_iso`.

    Kunci = tanggal ISO (YYYY-MM-DD), nilai = float ATAU dict berisi "score".
    Hanya memakai entri dengan tanggal <= (date_iso - lag_days),
    sehingga tidak ada lookahead: sentimen tanggal T baru boleh dipakai
    oleh sinyal di tanggal T + lag_days.
    """
    from datetime import date, timedelta

    if not sentiment_by_date:
        return None

    y, m, d = (int(x) for x in date_iso.split("-"))
    cutoff = date(y, m, d) - timedelta(days=lag_days)

    best_key = None
    for key in sentiment_by_date:
        ky, km, kd = (int(x) for x in key.split("-"))
        if date(ky, km, kd) <= cutoff:
            if best_key is None or key > best_key:
                best_key = key

    if best_key is None:
        return None

    value = sentiment_by_date[best_key]
    if isinstance(value, dict):
        return value.get("score")
    return value


# =====================================================================
# Sinyal per versi
# =====================================================================

def signals_v1(
    rows: list,
    buy_threshold: float = 70,
    sell_threshold: float = 30,
) -> list:
    """V1: teknikal saja. BUY >= buy_threshold, SELL < sell_threshold,
    selain itu HOLD (default 70/30 = baseline)."""
    signals = []
    for row in rows:
        score = calculate_technical_score(row)
        rec = generate_recommendation(
            score["technical_score"],
            score["condition"],
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
            trend_filter_ok=score["trend_filter_ok"],
        )
        signals.append({
            "timestamp": row["timestamp"],
            "price": row["price"],
            "atr": row.get("atr_14"),
            "technical_score": score["technical_score"],
            "condition": score["condition"],
            "trend_filter_ok": score["trend_filter_ok"],
            "sentiment_score": None,
            "final_score": None,
            "signal": rec["recommendation"],
        })
    return signals


def _sentiment_signal(
    score: float,
    buy_threshold: float = 60,
    sell_threshold: float = 40,
) -> str:
    """Threshold sentimen (default 60/40): >= buy BULLISH/BUY,
    < sell BEARISH/SELL."""
    if score >= buy_threshold:
        return BUY
    if score < sell_threshold:
        return SELL
    return HOLD


def signals_v3(
    rows: list,
    sentiment_by_date: dict,
    lag_days: int = 1,
    buy_threshold: float = 60,
    sell_threshold: float = 40,
) -> list:
    """V3: sentimen historis saja (tanpa indikator teknikal).

    Sinyal hari i memakai sentimen terbaru yang tersedia <= hari i - lag_days.
    Hari tanpa sentimen tersedia -> None (tidak ada eksekusi).
    """
    signals = []
    for row in rows:
        date_iso = _utc_date(row["timestamp"])
        score = sentiment_as_of(sentiment_by_date, date_iso, lag_days)

        signals.append({
            "timestamp": row["timestamp"],
            "price": row["price"],
            "atr": row.get("atr_14"),
            "technical_score": None,
            "condition": None,
            "sentiment_score": round(score, 2) if score is not None else None,
            "final_score": None,
            "signal": _sentiment_signal(
                score, buy_threshold, sell_threshold
            ) if score is not None else None,
        })
    return signals


def signals_v4(
    rows: list,
    sentiment_by_date: dict,
    lag_days: int = 1,
    buy_threshold: float = 70,
    sell_threshold: float = 30,
    technical_weight: float = 0.60,
) -> list:
    """V4: final_score = teknikal*bobot + sentimen*(1-bobot)
    (default 0.60/0.40 = baseline), threshold configurable (default 70/30).

    Sentimen memakai lag yang sama dengan V3 (anti-lookahead).
    """
    signals = []
    for row in rows:
        score = calculate_technical_score(row)
        date_iso = _utc_date(row["timestamp"])
        senti = sentiment_as_of(sentiment_by_date, date_iso, lag_days)

        if senti is None:
            # Tanpa sentimen tidak ada rekomendasi V4 -> tidak dieksekusi.
            final = None
            signal = None
        else:
            final = calculate_final_score(
                technical_score=score["technical_score"],
                sentiment_score=senti,
                technical_weight=technical_weight,
                buy_threshold=buy_threshold,
                sell_threshold=sell_threshold,
            )
            signal = final["recommendation"]
            # Trend Filter Rules: BUY teknikal ditolak saat harga di
            # bawah SMA 50/200 — berlaku juga pada komposit V4.
            if signal == BUY and not score["trend_filter_ok"]:
                signal = HOLD

        signals.append({
            "timestamp": row["timestamp"],
            "price": row["price"],
            "atr": row.get("atr_14"),
            "technical_score": score["technical_score"],
            "condition": score["condition"],
            "trend_filter_ok": score["trend_filter_ok"],
            "sentiment_score": round(senti, 2) if senti is not None else None,
            "final_score": final["final_score"] if final else None,
            "signal": signal,
        })
    return signals


def merge_sentiment_series(
    primary_by_date: dict, fallback_by_date: dict
) -> dict:
    """Gabung dua seri sentimen per tanggal (mis. berita per-koin vs FNG).

    `primary` (sentimen berita FinBERT per-koin) menang pada tanggal yang
    tersedia; `fallback` (FNG makro) hanya mengisi tanggal yang kosong.
    Penggabungan terjadi pada seri mentah sebelum lag anti-lookahead
    diterapkan, sehingga prioritas berita tidak membuka celah lookahead.
    """
    merged = dict(fallback_by_date or {})
    merged.update(primary_by_date or {})
    return merged