"""Mesin backtest murni (tanpa network).

Prinsip anti-lookahead yang dijamin di sini:
- Sinyal hari i hanya boleh memakai data <= hari i (dijamin oleh pemanggil).
- Sinyal hari i dieksekusi di harga hari i+1 (harga paling awal yang
  tersedia setelah sinyal dibuat).
- Return hari i -> i+1 hanya diakui ke posisi yang sudah dipegang
  *sebelum* eksekusi sinyal hari i.
- Stop-Loss / Take-Profit: keputusan dihitung dari harga penutupan hari T
  (data <= T) lalu dieksekusi di harga hari T+1 — sama-sama bebas lookahead.
- ATR Stop-Loss dinamis: level = harga entri − (ATR × multiplier) dengan ATR
  pada hari keputusan (data <= T), eksekusi di harga hari T+1 — identik
  dengan aturan SL/TP di atas (kedua stop aktif, yang tersentuh lebih dulu menang).
- ATR Trailing Stop: level = harga tertinggi sejak entri − (ATR × multiplier),
  `highest_price_since_entry` hanya memakai tutup hari <= T, eksekusi T+1.
"""

import math

BUY = "BUY"
HOLD = "HOLD"
SELL = "SELL"


def recommendation_from_score(
    score: float,
    buy_threshold: float = 70,
    sell_threshold: float = 30,
) -> str:
    """Threshold rekomendasi sesuai planning doc / generate_recommendation.

    BUY  : score >= buy_threshold  (default 70)
    SELL : score <  sell_threshold (default 30)
    HOLD : sisanya
    """
    if score >= buy_threshold:
        return BUY
    if score < sell_threshold:
        return SELL
    return HOLD


EXIT_SIGNAL = "SIGNAL"
EXIT_STOP_LOSS = "STOP_LOSS"
EXIT_TAKE_PROFIT = "TAKE_PROFIT"
EXIT_ATR_STOP_LOSS = "ATR_STOP_LOSS"
EXIT_TRAILING_STOP = "TRAILING_STOP"


def simulate(
    prices: list,
    signals: list,
    fee_rate: float = 0.0,
    stop_loss_pct: float = None,
    take_profit_pct: float = None,
    atr: list = None,
    use_atr_stop_loss: bool = True,
    atr_multiplier: float = 1.5,
    use_trailing_stop: bool = True,
) -> dict:
    """Simulasi long-only, all-in, dengan Stop-Loss / Take-Profit opsional.

    Parameters
    ----------
    prices : list[float]
        Harga per hari, sejajar dengan indeks hari.
    signals : list
        Panjang sama dengan `prices`. Elemen berupa dict dengan kunci
        ``signal`` (BUY/HOLD/SELL) atau ``None`` untuk hari tanpa sinyal
        (mis. warm-up) -> posisi dipertahankan, tidak ada eksekusi.
    fee_rate : float
        Fee per sisi eksekusi (0.001 = 0.1%).
    stop_loss_pct : float | None
        Jika diisi (mis. 0.03 = 3%), posisi terbuka dipaksa tutup saat
        perubahan harga dari harga entri menyentuh/melampaui batas ini
        (dihitung dari harga penutupan hari T, dieksekusi di harga hari
        T+1 -> tanpa lookahead, konsisten dengan aturan sinyal i -> i+1).
    take_profit_pct : float | None
        Sama seperti stop_loss_pct tapi untuk arah naik (TP).
    atr : list | None
        ATR sejajar `prices` (None = tanpa ATR -> ATR SL inert).
    use_atr_stop_loss : bool
        Aktifkan Stop-Loss dinamis berbasis ATR (default True; efektif
        hanya bila `atr` disediakan).
    atr_multiplier : float
        Pengali ATR (default 1.5). Level SL = entri − ATR × multiplier.
    use_trailing_stop : bool
        Aktifkan ATR Trailing Stop (default True; efektif hanya bila `atr`
        disediakan). Level = harga tertinggi sejak entri − ATR × multiplier
        (mengunci profit saat harga naik, mengikuti koreksi).

    Returns
    -------
    dict berisi equity_curve (sejajar prices), trades (round trip tertutup,
    masing-masing dengan ``exit_reason`` = SIGNAL | STOP_LOSS | ATR_STOP_LOSS |
    TRAILING_STOP | TAKE_PROFIT),
    n_executions, fees_paid_pct, open_trade (posisi masih terbuka di akhir).

    Catatan anti-lookahead & prioritas exit
    ---------------------------------------
    - Pada iterasi hari ``j``, keputusan SL/TP memakai harga penutupan
      hari ``j-1`` (data yang sudah tersedia) lalu dieksekusi di harga
      hari ``j`` — identik dengan mekanisme sinyal ``signals[j-1]``.    - SL/TP dievaluasi terlebih dahulu; pada hari yang sama dengan sinyal
      SELL, risiko (STOP_LOSS/ATR_STOP_LOSS/TRAILING_STOP/TAKE_PROFIT) yang
      menang. Sinyal BUY pada hari keluar paksa diabaikan (posisi baru
      dibuka kembali oleh sinyal BUY berikutnya).
    - ATR SL & Trailing: bila beberapa level risiko terpicu pada hari yang
      sama, exit_reason mengikuti level yang lebih dulu tersentuh (lebih
      ketat; trailing selalu >= ATR SL karena highest >= harga entri).
    """
    if len(prices) == 0:
        raise ValueError("prices kosong")
    if len(signals) != len(prices):
        raise ValueError(
            f"signals ({len(signals)}) harus sejajar prices ({len(prices)})"
        )
    if atr is not None and len(atr) != len(prices):
        raise ValueError(
            f"atr ({len(atr)}) harus sejajar prices ({len(prices)})"
        )

    n = len(prices)
    equity = 1.0
    equity_curve = [equity]
    positions = [0]  # posisi sesuai eksekusi di harga hari itu
    position = 0  # 0 = flat (cash), 1 = long
    open_equity = None
    open_price = None
    open_date_idx = None
    highest = None  # harga tertinggi sejak entri (untuk ATR trailing stop)
    trades = []
    n_executions = 0
    fees_paid_pct = 0.0

    for j in range(1, n):
        # 1) Akui return interval (j-1 -> j) untuk posisi yang dipegang
        #    selama interval tersebut (posisi hasil eksekusi di hari j-1,
        #    atau posisi yang sudah ada sebelumnya).
        if position == 1:
            ret = prices[j] / prices[j - 1] - 1.0
            equity *= 1.0 + ret
            # Perbarui harga tertinggi sejak entri (hanya data <= j-1).
            if prices[j - 1] > highest:
                highest = prices[j - 1]

        # 2) Cek Stop-Loss / Take-Profit berdasarkan harga penutupan
        #    hari j-1 (data <= j-1), eksekusi di harga hari j.
        #    SL% tetap dan ATR SL sama-sama diawasi; yang lebih dulu
        #    tersentuh (level lebih ketat) yang menang.
        target = None
        exit_reason = None
        if position == 1:
            close = prices[j - 1]
            change = close / open_price - 1.0

            atr_now = (
                atr[j - 1]
                if atr is not None and atr[j - 1] is not None
                else None
            )

            # Kumpulkan semua level risiko yang tersentuh berdasarkan harga
            # tutup hari j-1 (data <= j-1); yang paling ketat (level
            # tertinggi) yang menang -> atribusi exit jujur.
            risks = []
            if stop_loss_pct is not None and change <= -stop_loss_pct:
                risks.append(
                    (open_price * (1.0 - stop_loss_pct), EXIT_STOP_LOSS)
                )
            if use_atr_stop_loss and atr_now is not None:
                # Level SL dinamis: entri − ATR hari-keputusan × multiplier.
                atr_level = open_price - atr_now * atr_multiplier
                if close <= atr_level:
                    risks.append((atr_level, EXIT_ATR_STOP_LOSS))
            if use_trailing_stop and atr_now is not None:
                # Trailing: highest sejak entri − ATR × multiplier.
                trail_level = highest - atr_now * atr_multiplier
                if close <= trail_level:
                    risks.append((trail_level, EXIT_TRAILING_STOP))

            if risks:
                target = 0
                exit_reason = max(risks, key=lambda item: item[0])[1]
            elif take_profit_pct is not None and change >= take_profit_pct:
                target = 0
                exit_reason = EXIT_TAKE_PROFIT

        # 3) Eksekusi sinyal hari j-1 pada harga hari j
        #    (hanya jika tidak ada exit paksa dari SL/TP).
        sig = signals[j - 1]
        if target is None and sig is not None:
            s = sig["signal"] if isinstance(sig, dict) else sig
            if s == BUY:
                target = 1
            elif s == SELL:
                target = 0

        if target is not None and target != position:
            equity_before_fee = equity
            fee_cost = equity * fee_rate
            fees_paid_pct += fee_cost * 100.0
            equity -= fee_cost
            n_executions += 1

            if target == 1:
                # Acuan return round-trip: equity SEBELUM fee pembukaan,
                # sehingga return trade mencakup fee beli + fee jual.
                open_equity = equity_before_fee
                open_price = prices[j]
                open_date_idx = j
                highest = prices[j]  # titik awal trailing stop
            else:
                trades.append(
                    {
                        "entry_index": open_date_idx,
                        "exit_index": j,
                        "entry_price": open_price,
                        "exit_price": prices[j],
                        "return_pct": (equity / open_equity - 1.0) * 100.0,
                        "exit_reason": exit_reason or EXIT_SIGNAL,
                    }
                )
                open_equity = None
                open_price = None
                open_date_idx = None
                highest = None

            position = target

        equity_curve.append(equity)
        positions.append(position)

    open_trade = None
    if position == 1:
        open_trade = {
            "entry_index": open_date_idx,
            "entry_price": open_price,
            "last_price": prices[-1],
            "unrealized_pct": (equity / open_equity - 1.0) * 100.0,
        }

    return {
        "equity_curve": equity_curve,
        "positions": positions,
        "trades": trades,
        "n_executions": n_executions,
        "fees_paid_pct": fees_paid_pct,
        "open_trade": open_trade,
        "final_position": position,
    }


def max_drawdown_pct(equity_curve: list) -> float:
    """Drawdown maksimum (dalam %, positif) dari equity curve."""
    peak = equity_curve[0]
    max_dd = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        if peak > 0:
            dd = (peak - value) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd * 100.0


def sharpe_ratio(equity_curve: list, periods_per_year: float = 365.0):
    """Sharpe ratio annualisasi dari return harian equity curve."""
    rets = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]
        if prev > 0:
            rets.append(equity_curve[i] / prev - 1.0)

    if len(rets) < 2:
        return None

    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = math.sqrt(var)

    if std == 0:
        return 0.0
    return mean / std * math.sqrt(periods_per_year)


def signal_accuracy(prices: list, signals: list) -> dict:
    """Akurasi arah sinyal terhadap return hari berikutnya.

    Hanya sinyal BUY/SELL yang masuk hitungan (denominator eksplisit).
    Hari HOLD dilaporkan terpisah dengan rata-rata return-nya.
    """
    correct = 0
    directional = 0
    hold_count = 0
    hold_returns = []

    for i in range(len(prices) - 1):
        sig = signals[i]
        if sig is None:
            continue
        s = sig["signal"] if isinstance(sig, dict) else sig
        next_ret = prices[i + 1] / prices[i] - 1.0

        if s in (BUY, SELL):
            directional += 1
            if (s == BUY and next_ret > 0) or (s == SELL and next_ret < 0):
                correct += 1
        elif s == HOLD:
            hold_count += 1
            hold_returns.append(next_ret * 100.0)

    accuracy = (correct / directional * 100.0) if directional > 0 else None
    avg_hold = (
        sum(hold_returns) / len(hold_returns) if hold_returns else None
    )

    return {
        "n_directional_signals": directional,
        "n_correct": correct,
        "signal_accuracy_pct": round(accuracy, 2) if accuracy is not None else None,
        "n_hold_evaluated": hold_count,
        "hold_avg_next_return_pct": round(avg_hold, 2) if avg_hold is not None else None,
    }


def compute_metrics(
    prices: list,
    signals: list,
    sim: dict,
    start_index: int = 0,
) -> dict:
    """Agregasi metrik backtest.

    Parameters
    ----------
    prices : harga harian (evaluasi).
    signals : sinyal per hari (dict ``signal`` atau None).
    sim : hasil ``simulate`` untuk fee scenario yang sama.
    start_index : indeks hari pertama yang punya sinyal (window evaluasi);
        buy & hold dihitung dari harga hari itu.
    """
    equity_curve = sim["equity_curve"]

    total_return = (equity_curve[-1] - 1.0) * 100.0

    base = prices[start_index]
    buy_hold = (prices[-1] / base - 1.0) * 100.0

    acc = signal_accuracy(prices, signals)

    trades = sim["trades"]
    wins = [t for t in trades if t["return_pct"] > 0]
    losses = [t for t in trades if t["return_pct"] <= 0]
    win_rate = (len(wins) / len(trades) * 100.0) if trades else None

    n_stop_loss = sum(
        1 for t in trades if t.get("exit_reason") == EXIT_STOP_LOSS
    )
    n_atr_stop_loss = sum(
        1 for t in trades if t.get("exit_reason") == EXIT_ATR_STOP_LOSS
    )
    n_trailing_stop = sum(
        1 for t in trades if t.get("exit_reason") == EXIT_TRAILING_STOP
    )
    n_take_profit = sum(
        1 for t in trades if t.get("exit_reason") == EXIT_TAKE_PROFIT
    )

    gross_gain = sum(t["return_pct"] for t in wins)
    gross_loss = abs(sum(t["return_pct"] for t in losses))
    if trades and gross_loss > 0:
        profit_factor = gross_gain / gross_loss
    elif trades and gross_gain > 0:
        profit_factor = None  # tidak ada loss -> tak terhingga
    else:
        profit_factor = None

    signal_counts = {BUY: 0, HOLD: 0, SELL: 0, "none": 0}
    for sig in signals:
        if sig is None:
            signal_counts["none"] += 1
        else:
            s = sig["signal"] if isinstance(sig, dict) else sig
            signal_counts[s] = signal_counts.get(s, 0) + 1

    avg_trade = (
        sum(t["return_pct"] for t in trades) / len(trades) if trades else None
    )

    sharpe = sharpe_ratio(equity_curve)

    return {
        "n_days": len(prices),
        "n_eval_days": len(prices) - start_index,
        "total_return_pct": round(total_return, 2),
        "buy_hold_return_pct": round(buy_hold, 2),
        "excess_return_pct": round(total_return - buy_hold, 2),
        "max_drawdown_pct": round(max_drawdown_pct(equity_curve), 2),
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "n_executions": sim["n_executions"],
        "fees_paid_pct": round(sim["fees_paid_pct"], 3),
        "n_trades_closed": len(trades),
        "n_stop_loss_triggered": n_stop_loss,
        "n_atr_stop_loss_triggered": n_atr_stop_loss,
        "n_trailing_stop_triggered": n_trailing_stop,
        "n_take_profit_triggered": n_take_profit,
        "win_rate_pct": round(win_rate, 2) if win_rate is not None else None,
        "avg_trade_pct": round(avg_trade, 2) if avg_trade is not None else None,
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "open_trade_unrealized_pct": round(sim["open_trade"]["unrealized_pct"], 2)
        if sim["open_trade"]
        else None,
        "n_buy_signals": signal_counts[BUY],
        "n_hold_signals": signal_counts[HOLD],
        "n_sell_signals": signal_counts[SELL],
        "n_no_signal_days": signal_counts["none"],
        **acc,
    }
