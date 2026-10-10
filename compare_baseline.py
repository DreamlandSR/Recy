"""Perbandingan jujur: logika baseline LAMA vs perbaikan BARU.

Kedua lengan memakai data, window evaluasi, threshold, SL/TP, dan fee yang
sama persis (cache `backtest_results/cache/prices_bitcoin_365d.json`),
sehingga selisihnya murni berasal dari tiga perbaikan Phase 2:
  - trend filter SMA 50/200 (+ komponen skor baru)
  - pembobotan volume
  - ATR Stop-Loss dinamis

Lengan baseline meniru perilaku lama:
  - trend score hanya 2 komponen (price>sma20, ema20>sma20)
  - bobot 0.30/0.40/0.30 tanpa volume
  - tanpa trend filter (BUY tidak pernah diturunkan)
  - ATR SL nonaktif (simulate tanpa `atr`)

Pemakaian: .venv/Scripts/python compare_baseline.py
Tanpa network (murni cache lokal).
"""

import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.services.backtest_engine import compute_metrics, simulate
from app.services.backtest_service import build_technical_rows, signals_v1, signals_v3
from app.services.recommendation_service import generate_recommendation
from app.services.scoring_service import (
    calculate_momentum_score,
    calculate_volatility_score,
)
from run_backtest import (
    CACHE_DIR,
    HISTORY_DAYS,
    _first_signal_index,
    slice_eval_window,
)

COIN = "bitcoin"
DAYS = 90
BUY_T, SELL_T = 65, 35       # preset moderasi (sama dengan run_backtest)
SL, TP = 0.03, 0.06
ATR_MULT = 1.5
FEES = (0.0, 0.001)


def baseline_signal(row):
    """Skor & sinyal versi LAMA (tanpa SMA50/200, tanpa volume, tanpa filter)."""
    price = row["price"]
    sma_20 = row["sma_20"]
    ema_20 = row["ema_20"]

    trend = ((100 if price > sma_20 else 0) + (100 if ema_20 > sma_20 else 0)) / 2
    momentum = calculate_momentum_score(row)
    volatility = calculate_volatility_score(row)

    score = round(trend * 0.30 + momentum * 0.40 + volatility * 0.30, 2)
    condition = "BULLISH" if score >= 60 else ("NEUTRAL" if score >= 40 else "BEARISH")
    rec = generate_recommendation(
        score, condition, buy_threshold=BUY_T, sell_threshold=SELL_T
    )
    return {
        "timestamp": row["timestamp"],
        "price": price,
        "atr": None,
        "technical_score": score,
        "condition": condition,
        "signal": rec["recommendation"],
    }


def arm(name, sig, atr_enabled, start_index):
    prices = [s["price"] for s in sig]
    atr = [s.get("atr") for s in sig] if atr_enabled else None
    print(f"\n--- {name} (ATR SL {'ON' if atr_enabled else 'OFF'}) ---")
    print(f"{'fee':>6} {'ret%':>8} {'B&H%':>8} {'excess%':>8} {'maxDD%':>7} "
          f"{'sharpe':>7} {'trade':>5} {'SL/ATR/TP':>10} {'akurasi%':>9}")
    rows_out = []
    for fee in FEES:
        sim = simulate(
            prices, sig, fee_rate=fee,
            stop_loss_pct=SL, take_profit_pct=TP,
            atr=atr, use_atr_stop_loss=atr_enabled, atr_multiplier=ATR_MULT,
        )
        m = compute_metrics(prices, sig, sim, start_index=start_index)
        acc = m["signal_accuracy_pct"]
        print(
            f"{fee:>6.3f} {m['total_return_pct']:>8.2f} "
            f"{m['buy_hold_return_pct']:>8.2f} {m['excess_return_pct']:>8.2f} "
            f"{m['max_drawdown_pct']:>7.2f} "
            f"{(m['sharpe'] if m['sharpe'] is not None else 0):>7.2f} "
            f"{m['n_trades_closed']:>5} "
            f"{str(m['n_stop_loss_triggered']) + '/' + str(m['n_atr_stop_loss_triggered']) + '/' + str(m['n_take_profit_triggered']):>10} "
            f"{(acc if acc is not None else 0):>9.2f}"
        )
        rows_out.append(m)
    return rows_out


def compare(label, base, new):
    print(f"\n=== {label} (delta = baru - baseline) ===")
    for fee, b, n in zip(FEES, base, new):
        dd = n["max_drawdown_pct"] - b["max_drawdown_pct"]
        sh = (n["sharpe"] or 0) - (b["sharpe"] or 0)
        rt = n["total_return_pct"] - b["total_return_pct"]
        print(
            f"  fee {fee:g}: maxDD {b['max_drawdown_pct']:.2f} -> "
            f"{n['max_drawdown_pct']:.2f} ({dd:+.2f} {'LEBIH BAIK' if dd < 0 else 'lebih buruk'}) | "
            f"sharpe {(b['sharpe'] or 0):.2f} -> {(n['sharpe'] or 0):.2f} ({sh:+.2f} "
            f"{'LEBIH BAIK' if sh > 0 else 'lebih buruk'}) | "
            f"return {b['total_return_pct']:.2f} -> {n['total_return_pct']:.2f} ({rt:+.2f})"
        )


def new_signal_no_filter(row):
    """Skor BARU (dengan bobot volume) TANPA trend filter — untuk ablation."""
    from app.services.scoring_service import calculate_technical_score

    score = calculate_technical_score(row)
    rec = generate_recommendation(
        score["technical_score"],
        score["condition"],
        buy_threshold=BUY_T,
        sell_threshold=SELL_T,
    )
    return {
        "timestamp": row["timestamp"],
        "price": row["price"],
        "atr": row.get("atr_14"),
        "technical_score": score["technical_score"],
        "condition": score["condition"],
        "signal": rec["recommendation"],
    }


def main():
    cache = os.path.join(CACHE_DIR, f"prices_{COIN}_{HISTORY_DAYS}d.json")
    with open(cache, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    rows = build_technical_rows(data["prices"], data.get("volumes"))
    rows = slice_eval_window(rows, DAYS)
    print(f"{COIN}: {len(rows)} baris evaluasi "
          f"({len(data['prices'])} titik histori {HISTORY_DAYS} hari)")

    # ---- V1: teknikal saja --------------------------------------------
    sig_base = [baseline_signal(r) for r in rows]
    sig_new = signals_v1(rows, buy_threshold=BUY_T, sell_threshold=SELL_T)

    # window buy&hold yang sama untuk semua lengan
    sig_vol = [new_signal_no_filter(r) for r in rows]   # + volume, tanpa filter
    starts = [
        s for s in (
            _first_signal_index(sig_base),
            _first_signal_index(sig_vol),
            _first_signal_index(sig_new),
        )
        if s is not None
    ]
    start = max(starts)

    # ---- Ablasi V1 per fitur -----------------------------------------
    b1 = arm("V1 BASELINE (lama)", sig_base, False, start)
    a1 = arm("V1 + bobot volume (tanpa filter)", sig_vol, False, start)
    c1 = arm("V1 + volume + trend filter (tanpa ATR)", sig_new, False, start)
    n1 = arm("V1 PERBAIKAN penuh (filter + ATR)", sig_new, True, start)
    compare("V1 baseline -> penuh", b1, n1)
    print("\n=== Ablasi V1 (fee 0) ===")
    for label, res in [
        ("baseline (lama)", b1),
        ("+ volume", a1),
        ("+ trend filter", c1),
        ("+ ATR SL", n1),
    ]:
        m = res[0]
        print(
            f"  {label:<26} maxDD {m['max_drawdown_pct']:>6.2f}  "
            f"sharpe {(m['sharpe'] or 0):>6.2f}  return {m['total_return_pct']:>7.2f}  "
            f"trade {m['n_trades_closed']:>2}  B/H/S "
            f"{m['n_buy_signals']}/{m['n_hold_signals']}/{m['n_sell_signals']}"
        )

    # ---- V3: sentimen FNG (sinyal identik, bedanya hanya ATR SL) -------
    fng_path = os.path.join(CACHE_DIR, "fng_91d.json")
    if os.path.exists(fng_path):
        with open(fng_path, "r", encoding="utf-8") as fh:
            fng_raw = json.load(fh)
        fng = fng_raw["series"] if isinstance(fng_raw, dict) and "series" in fng_raw else fng_raw
        sig_v3 = signals_v3(rows, fng, buy_threshold=BUY_T, sell_threshold=SELL_T)
        start_v3 = _first_signal_index(sig_v3)
        b2 = arm("V3 BASELINE", sig_v3, False, start_v3)
        n2 = arm("V3 PERBAIKAN", sig_v3, True, start_v3)
        compare("V3 (sentimen FNG)", b2, n2)
    else:
        print(f"\n[skip] cache FNG tidak ditemukan: {fng_path}")


if __name__ == "__main__":
    main()
