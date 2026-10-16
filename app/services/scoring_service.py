# ============================================================================
# Mode Sensitivitas Sinyal / Trading Style (responsivitas BUY/HOLD/SELL)
# ============================================================================
#
# Ambang BUY/SELL per gaya trading:
# - scalp (Scalping / Day Trading): responsif — BUY >= 60, SELL < 40.
# - swing (Swing Trading, standar): lebih selektif — BUY >= 68, SELL < 32.
# - mode None (baseline lama)     : 70/30 — dipakai mesin backtest agar
#   perilaku & 29 unit test lama tidak bergeser tanpa sebab.
SIGNAL_MODES = {
    "scalp": {
        "buy": 60.0,
        "sell": 40.0,
        "label": "Scalping / Day Trading",
    },
    "swing": {
        "buy": 68.0,
        "sell": 32.0,
        "label": "Swing Trading",
    },
}
DEFAULT_SIGNAL_MODE = "swing"

# Penalti skor saat trend filter gagal TAPI momentum jangka pendek sedang
# breakout kuat (relaksasi SMA-200: berikan penalti, jangan langsung
# membatalkan sinyal ke HOLD — lihat assess_trend_filter).
TREND_BREAKOUT_PENALTY = 12.0


def mode_thresholds(mode: str = None) -> tuple:
    """(buy_threshold, sell_threshold) untuk mode sinyal.

    Mode tidak dikenal / None -> baseline lama 70/30.
    """
    cfg = SIGNAL_MODES.get((mode or "").strip().lower())
    if cfg:
        return cfg["buy"], cfg["sell"]
    return 70.0, 30.0


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


def momentum_breakout(data: dict, prev: dict = None) -> dict:
    """Deteksi breakout momentum jangka pendek (penentu relaksasi filter).

    Syarat "kuat" (semua terpenuhi):
    - MACD golden cross: garis MACD di atas signal DAN histogram > 0.
    - RSI zona bullish 50-78 (momentum naik, belum overbought ekstrem).
    - Menguat: bila baris sebelumnya (`prev`) tersedia — histogram naik,
      RSI naik, atau fresh golden cross (sebelumnya MACD <= signal).
      Tanpa `prev` syarat ini di-skip (evaluasi single-bar).

    Return {"ok": bool, "evidence": [str, ...]}.
    """
    rsi = data.get("rsi_14")
    macd = data.get("macd")
    signal_line = data.get("macd_signal")
    hist = data.get("macd_histogram")

    if rsi is None or macd is None or signal_line is None or hist is None:
        return {"ok": False, "evidence": []}

    macd_bull = macd > signal_line and hist > 0
    rsi_bull = 50.0 <= float(rsi) <= 78.0
    if not macd_bull or not rsi_bull:
        return {"ok": False, "evidence": []}

    evidence = ["MACD golden cross (histogram > 0)", f"RSI {rsi:.1f} zona bullish"]

    if prev:
        prev_hist = prev.get("macd_histogram")
        prev_rsi = prev.get("rsi_14")
        prev_macd = prev.get("macd")
        prev_signal = prev.get("macd_signal")
        fresh_cross = (
            prev_macd is not None and prev_signal is not None
            and prev_macd <= prev_signal
        )
        rising = (
            fresh_cross
            or (prev_hist is not None and hist > prev_hist)
            or (prev_rsi is not None and rsi > prev_rsi)
        )
        if not rising:
            return {"ok": False, "evidence": []}
        if fresh_cross:
            evidence.append("golden cross baru terbentuk")
        else:
            evidence.append("momentum menguat dari bar sebelumnya")

    return {"ok": True, "evidence": evidence}


def assess_trend_filter(data: dict, mode: str = None, prev: dict = None) -> dict:
    """Evaluasi trend filter sesuai trading style + relaksasi breakout.

    - mode None  : filter lama mutlak (SMA 50/200) — dipakai backtest.
    - mode "swing": filter standar SMA-50/SMA-200 + override mean-reversion.
    - mode "scalp": disesuaikan ke EMA-20 / EMA-50 timeframe aktif
      (bukan SMA-200 harian) — cocok untuk intraday.

    Relaksasi (semua mode aktif): bila filter gagal TAPI momentum sedang
    breakout kuat (momentum_breakout), berikan PENALTI skor
    (TREND_BREAKOUT_PENALTY) alih-alih memblokir mutlak ke HOLD.

    Return dict:
      raw_ok      : lolos filter mentah?
      status      : "pass" | "penalty" | "block"
      penalty     : poin skor yang dipotong (0 bila bukan penalty)
      ok          : efektif utk rekomendasi (False hanya saat block)
      mode        : mode dinormalisasi (None utk baseline)
      reason      : alasan manusiawi utk UI
    """
    key = (mode or "").strip().lower()
    mode = key if key in SIGNAL_MODES else None
    price = data["price"]

    if mode == "scalp":
        # Filter intraday: EMA-20 / EMA-50 pada timeframe aktif.
        ema_20 = data.get("ema_20")
        ema_50 = data.get("ema_50")
        raw_ok = not (
            (ema_20 is not None and price < ema_20)
            or (ema_50 is not None and price < ema_50)
        )
        fail_reason = "Harga di bawah EMA-20/EMA-50 timeframe aktif."
    else:
        raw_ok = trend_filter_ok(data)
        fail_reason = "Harga berada di bawah SMA-50 atau SMA-200 (kondisi bearish)."

    if raw_ok:
        return {
            "mode": mode, "raw_ok": True, "status": "pass",
            "penalty": 0.0, "ok": True, "reason": "",
        }

    # Baseline (mode None): filter tetap mutlak — dipakai mesin backtest
    # agar perilaku lama & walk-forward tidak berubah.
    if mode is None:
        return {
            "mode": None, "raw_ok": False, "status": "block",
            "penalty": 0.0, "ok": False, "reason": fail_reason,
        }

    # Relaksasi: momentum breakout kuat -> penalti skor, bukan blokir mutlak.
    momo = momentum_breakout(data, prev)
    if momo["ok"]:
        return {
            "mode": mode, "raw_ok": False, "status": "penalty",
            "penalty": TREND_BREAKOUT_PENALTY, "ok": True,
            "reason": (
                "Trend filter gagal, tapi momentum breakout kuat ("
                + "; ".join(momo["evidence"])
                + f") — skor dipotong {TREND_BREAKOUT_PENALTY:.0f} poin "
                "alih-alih dibatalkan."
            ),
        }

    return {
        "mode": mode, "raw_ok": False, "status": "block",
        "penalty": 0.0, "ok": False, "reason": fail_reason,
    }


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


def calculate_technical_score(data: dict, mode: str = None, prev: dict = None) -> dict:
    """Skor teknikal 0-100.

    - mode    : trading style ("scalp"/"swing") — mengaktifkan ambang
      mode_thresholds + filter EMA (scalp) + relaksasi penalti breakout.
      Mode None = perilaku baseline persis seperti lama (backtest).
    - prev    : baris indikator sebelumnya (untuk deteksi momentum
      menguat / fresh golden cross pada relaksasi trend filter).
    """
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

    # Trend filter: mode-aware (EMA untuk scalp, SMA untuk swing) + relaksasi
    # penalti bila momentum breakout kuat. Mode None -> filter lama mutlak.
    trend_filter = assess_trend_filter(data, mode=mode, prev=prev)
    if trend_filter["status"] == "penalty":
        technical_score = round(
            max(0.0, technical_score - trend_filter["penalty"]), 2
        )
    filter_ok = trend_filter["ok"]

    if technical_score >= 60:
        condition = "BULLISH"

    elif technical_score >= 40:
        condition = "NEUTRAL"

    else:
        condition = "BEARISH"

    buy_threshold, sell_threshold = mode_thresholds(mode)

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
        "condition": condition,
        # Detail trend filter utk UI (status pass/penalty/block + alasan).
        "trend_filter": trend_filter,
        # Ambang sinyal mode aktif (utk signal strength gauge di UI).
        "mode": trend_filter["mode"],
        "signal_thresholds": {
            "buy": buy_threshold,
            "sell": sell_threshold,
        },
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
