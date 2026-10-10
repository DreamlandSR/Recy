def generate_recommendation(
    technical_score: float,
    condition: str,
    buy_threshold: float = 70,
    sell_threshold: float = 30,
    trend_filter_ok: bool = True,
) -> dict:
    """Threshold rekomendasi configurable (default 70/30 = baseline lama).

    - BUY  : technical_score >= buy_threshold
    - SELL : technical_score <  sell_threshold
    - HOLD : sisanya (alasan mengikuti `condition` dari technical score)

    Trend Filter Rules (Tugas 1):
    - `trend_filter_ok=False` (harga di bawah SMA 50 atau SMA 200)
      -> sinyal BUY diabaikan (diturunkan ke HOLD) agar tidak merekomendasikan
      beli di pasar bearish. SELL/HOLD tidak terpengaruh.
    """

    if technical_score >= buy_threshold and not trend_filter_ok:
        recommendation = "HOLD"
        confidence = technical_score
        reason = [
            "Skor teknikal bullish, namun trend filter menolak BUY.",
            "Harga berada di bawah SMA 50 atau SMA 200 (kondisi bearish) "
            "— menunggu harga kembali di atas kedua moving average."
        ]

    elif technical_score >= buy_threshold:
        recommendation = "BUY"
        confidence = technical_score
        reason = [
            "Technical score menunjukkan kondisi bullish yang kuat.",
            "Trend, momentum, dan volatility mendukung kondisi positif."
        ]

    elif technical_score < sell_threshold:
        recommendation = "SELL"
        confidence = 100 - technical_score
        reason = [
            "Technical score menunjukkan kondisi bearish yang kuat.",
            "Trend, momentum, dan volatility cenderung mendukung kondisi negatif."
        ]

    elif condition == "BULLISH":
        recommendation = "HOLD"
        confidence = technical_score
        reason = [
            "Technical score menunjukkan kondisi bullish.",
            "Namun kekuatan sinyal belum cukup kuat untuk rekomendasi BUY."
        ]

    elif condition == "BEARISH":
        recommendation = "HOLD"
        confidence = 100 - technical_score
        reason = [
            "Technical score menunjukkan kondisi bearish.",
            "Namun sinyal belum cukup kuat untuk rekomendasi SELL."
        ]

    else:
        recommendation = "HOLD"
        confidence = 50
        reason = [
            "Technical score berada pada zona netral.",
            "Belum terdapat sinyal teknikal yang cukup kuat untuk BUY atau SELL."
        ]

    return {
        "recommendation": recommendation,
        "confidence": round(confidence, 2),
        "reason": reason
    }