# ============================================================================
# Parameter eksekusi riil (Personal Trading Edition — Tugas 1)
# ============================================================================

from app.services.scoring_service import mode_thresholds

# Kelas aset untuk alokasi modal (% dari total portofolio).
LARGE_CAP_COINS = {"bitcoin", "ethereum"}
ALLOCATION_LARGE_CAP = "10-15%"   # BTC / ETH (blue chip)
ALLOCATION_ALTCOIN = "3-5%"       # altcoin lain

# Fallback bila ATR tidak tersedia (data < 15 hari) — selaras dengan
# aturan backtest: SL 3% dan TP 6%.
DEFAULT_SL_PCT = 0.03
DEFAULT_TP_PCT = 0.06

# Pengali ATR untuk SL / TP (sesuai spesifikasi).
SL_ATR_MULT = 1.5
TP_ATR_MULT = 2.0


def _round_price(price: float) -> float:
    """Bulatkan harga sesuai magnitudonya agar angka tetap presisi."""
    price = float(price)
    if price >= 100:
        return round(price, 2)
    if price >= 1:
        return round(price, 4)
    if price >= 0.01:
        return round(price, 6)
    return round(price, 8)


def build_execution_plan(
    coin_id: str,
    current_price: float,
    atr_14: float = None,
    recommendation: str = "HOLD",
    price_source: str = "coingecko",
) -> dict:
    """Susun parameter eksekusi praktis dari harga saat ini + ATR 14.

    - stop_loss_price       : current_price - 1.5 * ATR14
                              (fallback: -3% bila ATR tidak tersedia)
    - take_profit_price     : current_price + 2.0 * ATR14
                              (fallback: +6% bila ATR tidak tersedia)
    - trailing_stop_trigger : kapan mulai menggeser trailing stop
    - risk_reward_ratio     : potensi profit : potensi risiko ("1 : X")
    - suggested_allocation_pct: porsi modal (BTC/ETH 10-15%, altcoin 3-5%)

    Semua angka bersifat informatif — bukan nasihat investasi.

    `price_source` : asal `current_price` ("binance" = harga live bursa,
        "coingecko" = fallback harian) — diteruskan ke UI sebagai label
        sumber harga agar pengguna tahu apakah angka sudah real-time.
    """
    current_price = float(current_price)

    has_atr = (
        atr_14 is not None
        and float(atr_14) > 0
        and current_price > 0
    )

    atr = None
    if has_atr:
        atr = float(atr_14)
        stop_loss = current_price - (SL_ATR_MULT * atr)
        take_profit = current_price + (TP_ATR_MULT * atr)
        atr_source = f"{SL_ATR_MULT}x ATR14 SL / {TP_ATR_MULT}x ATR14 TP"

        # Guard: ATR tidak wajar bila SL <= 0 -> pakai fallback persen.
        if stop_loss <= 0:
            stop_loss = current_price * (1 - DEFAULT_SL_PCT)
            take_profit = current_price * (1 + DEFAULT_TP_PCT)
            atr = None
            atr_source = (
                f"default -{DEFAULT_SL_PCT:.0%}/+{DEFAULT_TP_PCT:.0%} "
                "(ATR14 tidak wajar)"
            )
    else:
        # Fallback persis seperti aturan backtest: SL 3%, TP 6%.
        stop_loss = current_price * (1 - DEFAULT_SL_PCT)
        take_profit = current_price * (1 + DEFAULT_TP_PCT)
        atr_source = (
            f"default -{DEFAULT_SL_PCT:.0%}/+{DEFAULT_TP_PCT:.0%} "
            "(ATR14 tidak tersedia)"
        )

    stop_loss_raw = stop_loss
    take_profit_raw = take_profit
    stop_loss = _round_price(stop_loss)
    take_profit = _round_price(take_profit)

    # Rasio reward:risk — jarak dari harga saat ini (dihitung dari nilai
    # mentah sebelum pembulatan output agar presisi pada harga kecil).
    risk = current_price - stop_loss_raw
    reward = take_profit_raw - current_price
    risk_reward_value = round(reward / risk, 2) if risk > 0 else None

    # Trailing stop mulai digeser setelah kenaikan menutupi jarak risiko
    # (harga naik minimal sebesar jarak SL) -> saat trailing mulai bergerak,
    # posisi sudah di zona profit.
    trigger_price = current_price + risk
    trigger_pct = (risk / current_price * 100) if current_price > 0 else 0.0

    if atr is not None:
        trailing_stop_trigger = (
            f"Trigger saat harga >= {_round_price(trigger_price)} "
            f"(+{trigger_pct:.1f}% dari entry). Setelah tercapai, geser SL "
            f"mengikuti tertinggi: SL = harga tertinggi - {SL_ATR_MULT}x ATR14 "
            f"({SL_ATR_MULT * atr:.2f} saat ini)."
        )
    else:
        trailing_stop_trigger = (
            f"Trigger saat harga >= {_round_price(trigger_price)} "
            f"(+{trigger_pct:.1f}% dari entry). Setelah tercapai, geser SL "
            f"mengikuti tertinggi (kunci profit) — ATR14 tidak tersedia, "
            f"pakai jarak trailing ~3% dari harga tertinggi."
        )

    # Konteks sesuai sinyal (crypto spot, tanpa short).
    if recommendation == "BUY":
        note = (
            f"Entry di sekitar {_round_price(current_price)}; pasang SL "
            f"{stop_loss} dan TP {take_profit} sebelum entry."
        )
    elif recommendation == "SELL":
        note = (
            f"Sinyal jual — jika masih hold, {stop_loss} adalah batas "
            f"risiko terakhir; jangan entry baru."
        )
    else:
        note = (
            f"Belum ada sinyal entry kuat; jika sudah punya posisi, jadikan "
            f"{stop_loss} sebagai pelindung dan {take_profit} sebagai target."
        )

    coin_key = (coin_id or "").strip().lower()
    if coin_key in LARGE_CAP_COINS:
        allocation = ALLOCATION_LARGE_CAP
        allocation_note = (
            "Kelas large-cap (BTC/ETH): porsi lebih besar "
            "tapi tetap terdiversifikasi."
        )
    else:
        allocation = ALLOCATION_ALTCOIN
        allocation_note = (
            "Altcoin: porsi kecil (3-5%) karena volatilitas lebih tinggi."
        )

    return {
        "current_price": _round_price(current_price),
        "price_source": price_source,
        "stop_loss_price": stop_loss,
        "take_profit_price": take_profit,
        "trailing_stop_trigger": trailing_stop_trigger,
        "risk_reward_ratio": (
            f"1 : {risk_reward_value}" if risk_reward_value else "n/a"
        ),
        "suggested_allocation_pct": allocation,
        # Konteks tambahan (berguna untuk eksekusi manual):
        "atr_14": round(atr, 4) if atr is not None else None,
        "sl_distance_pct": (
            round(risk / current_price * 100, 2)
            if current_price > 0 else None
        ),
        "tp_distance_pct": (
            round(reward / current_price * 100, 2)
            if current_price > 0 else None
        ),
        "risk_reward_value": risk_reward_value,
        "calculation_source": atr_source,
        "allocation_note": allocation_note,
        "note": note,
    }


def signal_label(recommendation: str, technical_score: float,
                 buy_threshold: float, sell_threshold: float) -> str:
    """Label kekuatan sinyal utk Signal Strength Gauge (UI).

    - "Strong BUY"  : skor jauh di atas ambang BUY (>= ambang + 8).
    - "Weak BUY"    : baru saja menembus ambang.
    - "Strong SELL" : skor jauh di bawah ambang SELL (<= ambang - 8).
    - "Weak SELL"   : baru saja menembus ambang.
    - "Near BUY" / "Near SELL" : HOLD yang sudah dekat ambang
      (pengguna tahu seberapa cepat sinyal bisa berbalik).
    - "Neutral HOLD": HOLD di zona netral.
    """
    score = float(technical_score)
    if recommendation == "BUY":
        return "Strong BUY" if score >= buy_threshold + 8 else "Weak BUY"
    if recommendation == "SELL":
        return "Strong SELL" if score <= sell_threshold - 8 else "Weak SELL"
    if score >= buy_threshold - 6:
        return "Near BUY"
    if score < sell_threshold + 6:
        return "Near SELL"
    return "Neutral HOLD"


def signal_from_score(
    technical_score: float,
    condition: str,
    buy_threshold: float = None,
    sell_threshold: float = None,
    trend_filter_ok: bool = True,
    mode: str = None,
) -> dict:
    """Keputusan sinyal (BUY/HOLD/SELL) + kekuatan sinyal utk gauge.

    Threshold per trading style saat `mode` diberikan ("scalp" 60/40,
    "swing" 68/32); tanpa mode & tanpa threshold eksplisit -> baseline
    70/30 (perilaku lama — dipakai backtest).

    Output tambahan:
    - signal_strength : derajat keyakinan 0-100 (= skor teknikal).
    - signal_label    : "Strong BUY" / "Weak BUY" / "Neutral HOLD" /
      "Near BUY" / "Strong SELL" dst — menunjukkan seberapa dekat
      koin dengan pembalikan arah sinyal.
    - buy_threshold / sell_threshold / mode : ambang yang dipakai
      (diteruskan ke UI agar gauge menampilkan ambang aktif).
    """
    default_buy, default_sell = mode_thresholds(mode)
    if buy_threshold is None:
        buy_threshold = default_buy
    if sell_threshold is None:
        sell_threshold = default_sell

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
        "reason": reason,
        # Signal Strength Gauge (Phase 11): kekuatan keyakinan sinyal.
        "signal_strength": round(float(technical_score), 2),
        "signal_label": signal_label(
            recommendation, technical_score, buy_threshold, sell_threshold
        ),
        "buy_threshold": buy_threshold,
        "sell_threshold": sell_threshold,
        "mode": mode,
    }


def generate_recommendation(
    technical_score: float,
    condition: str,
    buy_threshold: float = None,
    sell_threshold: float = None,
    trend_filter_ok: bool = True,
    coin_id: str = None,
    current_price: float = None,
    atr_14: float = None,
    price_source: str = "coingecko",
    mode: str = None,
) -> dict:
    """Rekomendasi sinyal + blok eksekusi (SL/TP dari ATR).

    - BUY  : technical_score >= buy_threshold
    - SELL : technical_score <  sell_threshold
    - HOLD : sisanya (alasan mengikuti `condition` dari technical score)

    Threshold:
    - `mode` ("scalp" 60/40 · "swing" 68/32) menentukan ambang saat
      buy/sell threshold tidak diberikan eksplisit — lihat
      `signal_from_score`. Tanpa mode & tanpa threshold -> baseline 70/30.

    Trend Filter Rules (Tugas 1):
    - `trend_filter_ok=False` (harga di bawah SMA 50 atau SMA 200)
      -> sinyal BUY diabaikan (diturunkan ke HOLD) agar tidak merekomendasikan
      beli di pasar bearish. SELL/HOLD tidak terpengaruh. (Catatan Phase 11:
      di mode scalp/swing, `calculate_technical_score` sudah mengubah skor
      dengan penalti bila momentum breakout kuat — sehingga filter di sini
      hanya memblokir bila relaksasi tidak berlaku.)

    Parameter eksekusi (Personal Trading Edition):
    - Bila `current_price` diberikan, hasil menyertakan blok `execution`
      (SL/TP dari ATR, trailing trigger, risk:reward, alokasi modal) via
      `build_execution_plan`. `price_source` diteruskan ke blok execution
      ("binance" bila harga live bursa dipakai, selain itu "coingecko").
    """

    result = signal_from_score(
        technical_score,
        condition,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        trend_filter_ok=trend_filter_ok,
        mode=mode,
    )

    if current_price is not None:
        result["execution"] = build_execution_plan(
            coin_id=coin_id,
            current_price=current_price,
            atr_14=atr_14,
            recommendation=result["recommendation"],
            price_source=price_source,
        )

    return result