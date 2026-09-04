def calculate_trend_score(data: dict) -> float:
    price = data["price"]
    sma_20 = data["sma_20"]
    ema_20 = data["ema_20"]

    price_vs_sma = 100 if price > sma_20 else 0

    ema_vs_sma = 100 if ema_20 > sma_20 else 0

    trend_score = (
        price_vs_sma +
        ema_vs_sma
    ) / 2

    return trend_score


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
        macd_line_score +
        histogram_score
    ) / 2

    # RSI dan MACD memiliki bobot sama
    momentum_score = (
        (rsi_score * 0.50) +
        (macd_score * 0.50)
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


def calculate_technical_score(data: dict) -> dict:
    trend_score = calculate_trend_score(data)

    momentum_score = calculate_momentum_score(data)

    volatility_score = calculate_volatility_score(data)

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

    return {
        "trend_score": round(trend_score, 2),
        "momentum_score": round(momentum_score, 2),
        "volatility_score": round(volatility_score, 2),
        "technical_score": technical_score,
        "condition": condition
    }