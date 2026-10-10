def classify_regime(data: dict) -> str:
    """Rezim pasar dari ADX 14 (Phase 3).

    - TRENDING  : ADX >= 25 (trend kuat -> bobot trend following dominan)
    - SIDEWAYS  : ADX <  20 (ranging -> bobot oscillator dominan)
    - TRANSITION: 20 <= ADX < 25 (zona peralihan -> bobot netral Phase 2)
    - UNKNOWN   : ADX belum terisi (None) -> bobot netral Phase 2
    """
    adx = data.get("adx_14")
    if adx is None:
        return "UNKNOWN"
    if adx >= 25:
        return "TRENDING"
    if adx < 20:
        return "SIDEWAYS"
    return "TRANSITION"


# Bobot (trend, momentum, volatility, volume) per rezim ADX.
# TRENDING : trend following dominan — EMA 20 (di trend_score) & MACD
#            (di momentum_score) ditekankan; volatilitas diturunkan.
# SIDEWAYS : oscillator dominan — RSI (momentum) & Bollinger (volatility)
#            dinaikkan; trend following diturunkan.
REGIME_WEIGHTS = {
    "TRENDING": (0.40, 0.35, 0.10, 0.15),
    "SIDEWAYS": (0.15, 0.30, 0.40, 0.15),
    "TRANSITION": (0.30, 0.35, 0.20, 0.15),
    "UNKNOWN": (0.30, 0.35, 0.20, 0.15),
}


def calculate_trend_score(data: dict) -> float:
    price = data["price"]
    sma_20 = data["sma_20"]
    ema_20 = data["ema_20"]

    # Komponen tersedia (0 atau 100). SMA 50/200 bisa None sampai
    # jendelanya terisi (data < 50 / < 200 hari) -> komponen di-skip,
    # rata-rata dihitung hanya di antara yang tersedia (NaN-safe).
    checks = [
        100 if price > sma_20 else 0,
        100 if ema_20 > sma_20 else 0,
    ]

    sma_50 = data.get("sma_50")
    sma_200 = data.get("sma_200")

    # (1) tren menengah: harga di atas SMA 50
    if sma_50 is not None:
        checks.append(100 if price > sma_50 else 0)

    # (2) tren makro / Golden Cross: SMA 50 di atas SMA 200
    if sma_50 is not None and sma_200 is not None:
        checks.append(100 if sma_50 > sma_200 else 0)

    trend_score = sum(checks) / len(checks)

    return trend_score


def trend_filter_ok(data: dict) -> bool:
    """Trend Filter Rules: False bila harga di bawah SMA 50 ATAU SMA 200.

    Mencegah rekomendasi beli di pasar bearish. SMA yang belum terisi
    (None) di-skip — filter hanya menilai jendela yang tersedia.

    Override Phase 3 (mean-reversion): pada rezim SIDEWAYS (ADX < 20) dengan
    RSI < 35 (oversold), syarat SMA 50 DILONGGARKAN — BUY di bawah SMA 50
    diijinkan untuk menangkap momen beli saat harga diskon. Syarat SMA 200
    tetap berlaku mutlak (makro bearish tetap diblokir).
    """
    price = data["price"]
    sma_50 = data.get("sma_50")
    sma_200 = data.get("sma_200")

    adx = data.get("adx_14")
    rsi = data.get("rsi_14")
    mean_reversion_ok = (
        adx is not None and adx < 20
        and rsi is not None and rsi < 35
    )

    if sma_50 is not None and price < sma_50 and not mean_reversion_ok:
        return False
    if sma_200 is not None and price < sma_200:
        return False
    return True


def calculate_momentum_score(data: dict) -> float:
    rsi = data["rsi_14"]

    macd = data["macd"]
    macd_signal = data["macd_signal"]
    macd_histogram = data["macd_histogram"]

    # =========================
    # RSI SCORE
    # =========================

    if rsi < 30:
        rsi_score = 65

    elif rsi < 50:
        rsi_score = 45

    elif rsi <= 70:
        rsi_score = 70

    else:
        rsi_score = 35

    # =========================
    # MACD SCORE
    # =========================

    macd_line_score = (
        70 if macd > macd_signal else 30
    )

    histogram_score = (
        70 if macd_histogram > 0 else 30
    )

    macd_score = (
        macd_line_score + histogram_score
    ) / 2

    # RSI dan MACD memiliki bobot sama
    momentum_score = (
        (rsi_score * 0.50) + (macd_score * 0.50)
    )

    return momentum_score


def calculate_volatility_score(data: dict) -> float:
    bb_position = data["bb_position"]

    if bb_position < 0.20:
        volatility_score = 70

    elif bb_position <= 0.80:
        volatility_score = 50

    else:
        volatility_score = 30

    return volatility_score


def calculate_volume_score(data: dict) -> float:
    """Skor konfirmasi volume berdasarkan volume_ratio & arah harga.

    - volume_ratio > 1.2 saat harga naik (breakout) -> 75 (konfirmasi
      tinggi; kisaran 70-80 sesuai spesifikasi).
    - volume rendah saat harga naik -> 35 (menyaring fake breakout;
      kisaran 30-40 sesuai spesifikasi).
    - volume tinggi saat harga turun -> 30 (distribution/penjualan).
    - Netral (50) bila data volume tidak tersedia.
    """
    ratio = data.get("volume_ratio")
    change = data.get("price_change_pct")

    if ratio is None or change is None:
        return 50.0

    price_rising = change > 0

    if ratio >= 1.2:
        return 75.0 if price_rising else 30.0
    if price_rising:
        return 55.0 if ratio >= 0.8 else 35.0
    return 45.0


def calculate_technical_score(data: dict) -> dict:
    trend_score = calculate_trend_score(data)

    momentum_score = calculate_momentum_score(data)

    volatility_score = calculate_volatility_score(data)

    volume_score = calculate_volume_score(data)

    has_volume = data.get("volume_ratio") is not None

    regime = classify_regime(data)

    if has_volume:
        # Phase 3: bobot mengikuti rezim pasar (ADX).
        w_trend, w_mom, w_volatility, w_volume = REGIME_WEIGHTS[regime]
        technical_score = (
            (trend_score * w_trend) +
            (momentum_score * w_mom) +
            (volatility_score * w_volatility) +
            (volume_score * w_volume)
        )
    else:
        # Fallback bobot lama (0.30/0.40/0.30) saat data volume absen,
        # agar skor API/backtest lama tidak bergeser tanpa sebab.
        technical_score = (
            (trend_score * 0.30) +
            (momentum_score * 0.40) +
            (volatility_score * 0.30)
        )

    technical_score = round(
        technical_score,
        2
    )

    if technical_score >= 60:
        condition = "BULLISH"

    elif technical_score >= 40:
        condition = "NEUTRAL"

    else:
        condition = "BEARISH"

    filter_ok = trend_filter_ok(data)

    return {
        "trend_score": round(trend_score, 2),
        "momentum_score": round(momentum_score, 2),
        "volatility_score": round(volatility_score, 2),
        "volume_score": round(volume_score, 2),
        "has_volume": has_volume,
        "adx_14": round(data.get("adx_14"), 2)
        if data.get("adx_14") is not None else None,
        "regime": regime,
        "trend_filter_ok": filter_ok,
        "technical_score": technical_score,
        "condition": condition
    }


def calculate_final_score(
    technical_score: float,
    sentiment_score: float,
    technical_weight: float = 0.60,
    buy_threshold: float = 70,
    sell_threshold: float = 30,
) -> dict:
    """final_score = teknikal*bobot + sentimen*(1-bobot), threshold configurable.

    Default bobot 0.60/0.40 dan threshold 70/30 = perilaku baseline lama.
    """

    sentiment_weight = 1.0 - technical_weight

    final_score = (
        (technical_score * technical_weight) +
        (sentiment_score * sentiment_weight)
    )

    final_score = round(final_score, 2)

    if final_score >= buy_threshold:
        recommendation = "BUY"

    elif final_score < sell_threshold:
        recommendation = "SELL"

    else:
        recommendation = "HOLD"

    if final_score >= 60:
        condition = "BULLISH"

    elif final_score >= 40:
        condition = "NEUTRAL"

    else:
        condition = "BEARISH"

    return {
        "final_score": final_score,
        "condition": condition,
        "recommendation": recommendation
    }
