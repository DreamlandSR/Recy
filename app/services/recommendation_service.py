# ============================================================================
# Parameter eksekusi riil (Personal Trading Edition — Tugas 1)
# ============================================================================

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


def generate_recommendation(
    technical_score: float,
    condition: str,
    buy_threshold: float = 70,
    sell_threshold: float = 30,
    trend_filter_ok: bool = True,
    coin_id: str = None,
    current_price: float = None,
    atr_14: float = None,
    price_source: str = "coingecko",
) -> dict:
    """Threshold rekomendasi configurable (default 70/30 = baseline lama).

    - BUY  : technical_score >= buy_threshold
    - SELL : technical_score <  sell_threshold
    - HOLD : sisanya (alasan mengikuti `condition` dari technical score)

    Trend Filter Rules (Tugas 1):
    - `trend_filter_ok=False` (harga di bawah SMA 50 atau SMA 200)
      -> sinyal BUY diabaikan (diturunkan ke HOLD) agar tidak merekomendasikan
      beli di pasar bearish. SELL/HOLD tidak terpengaruh.

    Parameter eksekusi (Personal Trading Edition):
    - Bila `current_price` diberikan, hasil menyertakan blok `execution`
      (SL/TP dari ATR, trailing trigger, risk:reward, alokasi modal) via
      `build_execution_plan`. `price_source` diteruskan ke blok execution
      ("binance" bila harga live bursa dipakai, selain itu "coingecko").
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

    result = {
        "recommendation": recommendation,
        "confidence": round(confidence, 2),
        "reason": reason
    }

    if current_price is not None:
        result["execution"] = build_execution_plan(
            coin_id=coin_id,
            current_price=current_price,
            atr_14=atr_14,
            recommendation=recommendation,
            price_source=price_source,
        )

    return result