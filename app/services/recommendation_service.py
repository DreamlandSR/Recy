def generate_recommendation(technical_score: float, condition: str) -> dict:

    if technical_score >= 70:
        recommendation = "BUY"
        confidence = technical_score
        reason = [
            "Technical score menunjukkan kondisi bullish yang kuat.",
            "Trend, momentum, dan volatility mendukung kondisi positif."
        ]

    elif technical_score >= 60:
        recommendation = "HOLD"
        confidence = technical_score
        reason = [
            "Technical score menunjukkan kondisi bullish.",
            "Namun kekuatan sinyal belum cukup kuat untuk rekomendasi BUY."
        ]

    elif technical_score >= 40:
        recommendation = "HOLD"
        confidence = 50
        reason = [
            "Technical score berada pada zona netral.",
            "Belum terdapat sinyal teknikal yang cukup kuat untuk BUY atau SELL."
        ]

    elif technical_score >= 30:
        recommendation = "HOLD"
        confidence = 100 - technical_score
        reason = [
            "Technical score menunjukkan kondisi bearish.",
            "Namun sinyal belum cukup kuat untuk rekomendasi SELL."
        ]

    else:
        recommendation = "SELL"
        confidence = 100 - technical_score
        reason = [
            "Technical score menunjukkan kondisi bearish yang kuat.",
            "Trend, momentum, dan volatility cenderung mendukung kondisi negatif."
        ]

    return {
        "recommendation": recommendation,
        "confidence": round(confidence, 2),
        "reason": reason
    }