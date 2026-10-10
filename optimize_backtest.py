"""Grid search optimasi parameter backtest Recy.

Menguji kombinasi parameter:
  buy_threshold x sell_threshold x stop_loss_pct x take_profit_pct

pada strategi V1 (teknikal) dan/atau V4 (teknikal + sentimen), lalu mencetak
tabel peringkat berdasarkan:
  1. Sharpe Ratio (annualisasi), dan
  2. Excess Return vs Buy & Hold.

Hasil penuh disimpan ke ``backtest_results/optimization.csv``.

Pemakaian:
  .venv/Scripts/python optimize_backtest.py
  .venv/Scripts/python optimize_backtest.py --strategies v1 --coins bitcoin
  .venv/Scripts/python optimize_backtest.py \
      --buy-list 55,60,65,70 --sell-list 30,35,40,45 \
      --sl-list 0,0.03,0.05 --tp-list 0,0.06,0.10 \
      --tech-weight 0.70 --top 15

Catatan anti-lookahead: seluruh grid memakai pipeline sinyal yang sama
(data <= hari i, eksekusi hari i+1; SL/TP ditutup pada harga hari berikutnya
setelah terpicu) — tidak ada data masa depan yang dipakai.

Peringatan: optimasi dilakukan pada window yang sama dengan backtest
(**in-sample**) sehingga berisiko overfitting. Angka terbaik bukan jaminan
performa masa depan; validasi walk-forward diperlukan sebelum produksi.
"""

import argparse
import asyncio
import csv
import itertools
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Konsol Windows (cp1252) -> paksa UTF-8 agar tabel tidak gagal.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.services.backtest_engine import compute_metrics, simulate
from app.services.backtest_service import (
    _utc_date,
    build_technical_rows,
    signals_v1,
    signals_v4,
)
from app.services.sentiment_history_service import get_fng_history
from run_backtest import (
    CACHE_DIR,
    COIN_LABEL,
    FEE_RATE,
    HISTORY_DAYS,
    OUT_DIR,
    PRIMARY_COIN,
    _first_signal_index,
    build_v4_sentiment,
    fetch_prices,
    log,
    slice_eval_window,
)

DEFAULT_STRATEGIES = "v1,v4"
DEFAULT_BUY_LIST = "55,60,65,70"
DEFAULT_SELL_LIST = "30,35,40,45"
DEFAULT_SL_LIST = "0,0.03,0.05"      # 0 = tanpa SL
DEFAULT_TP_LIST = "0,0.06,0.10"      # 0 = tanpa TP

OPTIMIZATION_CSV = os.path.join(OUT_DIR, "optimization.csv")

RESULT_FIELDS = [
    "strategy", "coin", "buy_threshold", "sell_threshold",
    "stop_loss_pct", "take_profit_pct",
    "fee_rate", "start_date", "end_date", "n_eval_days",
    "n_buy_signals", "n_hold_signals", "n_sell_signals",
    "n_directional_signals", "n_correct", "signal_accuracy_pct",
    "total_return_pct", "buy_hold_return_pct", "excess_return_pct",
    "max_drawdown_pct", "sharpe", "n_executions", "fees_paid_pct",
    "n_trades_closed", "n_stop_loss_triggered", "n_take_profit_triggered",
    "win_rate_pct", "avg_trade_pct", "profit_factor",
    "open_trade_unrealized_pct",
]


def parse_list(text: str, cast=float) -> list:
    return [cast(x.strip()) for x in text.split(",") if x.strip()]


def fmt_opt(value, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def print_table(title: str, ranked: list, top: int):
    print(f"\n=== {title} (top {min(top, len(ranked))} dari {len(ranked)} kombinasi) ===")
    header = (
        f"{'#':>3}  {'strat':<5} {'koin':<4} {'buy':>4} {'sell':>4} "
        f"{'SL':>5} {'TP':>5} {'ret%':>8} {'B&H%':>7} {'excess%':>8} "
        f"{'sharpe':>7} {'dd%':>6} {'trade':>5} {'SL/TP':>6} {'win%':>6}"
    )
    print(header)
    print("-" * len(header))
    for rank, row in enumerate(ranked[:top], start=1):
        sl = row["stop_loss_pct"]
        tp = row["take_profit_pct"]
        sl_txt = f"{sl:.0%}" if sl else "-"
        tp_txt = f"{tp:.0%}" if tp else "-"
        sltp = (
            f"{row['n_stop_loss_triggered']}/{row['n_take_profit_triggered']}"
        )
        coin = COIN_LABEL.get(row["coin"], row["coin"])
        print(
            f"{rank:>3}  {row['strategy']:<5} {coin:<4} "
            f"{row['buy_threshold']:>4g} {row['sell_threshold']:>4g} "
            f"{sl_txt:>5} {tp_txt:>5} "
            f"{fmt_opt(row['total_return_pct']):>8} "
            f"{fmt_opt(row['buy_hold_return_pct']):>7} "
            f"{fmt_opt(row['excess_return_pct']):>8} "
            f"{fmt_opt(row['sharpe']):>7} "
            f"{fmt_opt(row['max_drawdown_pct']):>6} "
            f"{row['n_trades_closed']:>5} {sltp:>6} "
            f"{fmt_opt(row['win_rate_pct']):>6}"
        )


async def main():
    parser = argparse.ArgumentParser(
        description="Grid search parameter backtest Recy (Sharpe & Excess Return)"
    )
    parser.add_argument(
        "--strategies", default=DEFAULT_STRATEGIES,
        help="daftar strategi, mis. v1,v4 (default: v1,v4)",
    )
    parser.add_argument(
        "--coins", default="",
        help="koin dipisah koma (default: bitcoin)",
    )
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument(
        "--buy-list", default=DEFAULT_BUY_LIST,
        help="kandidat buy_threshold, mis. 55,60,65,70",
    )
    parser.add_argument(
        "--sell-list", default=DEFAULT_SELL_LIST,
        help="kandidat sell_threshold, mis. 30,35,40,45",
    )
    parser.add_argument(
        "--sl-list", default=DEFAULT_SL_LIST,
        help="kandidat stop_loss_pct; 0 = tanpa SL (default: 0,0.03,0.05)",
    )
    parser.add_argument(
        "--tp-list", default=DEFAULT_TP_LIST,
        help="kandidat take_profit_pct; 0 = tanpa TP (default: 0,0.06,0.10)",
    )
    parser.add_argument(
        "--fee", type=float, default=FEE_RATE,
        help="fee per sisi (default 0.001 = 0,1%)",
    )
    parser.add_argument(
        "--tech-weight", type=float, default=0.70,
        help="bobot teknikal V4 (default 0.70)",
    )
    parser.add_argument(
        "--skip-news", action="store_true",
        help="V4 tanpa berita per-koin (pakai FNG saja)",
    )
    parser.add_argument("--top", type=int, default=15,
                        help="jumlah baris per tabel peringkat (default 15)")
    args = parser.parse_args()

    strategies = [s.strip().lower() for s in args.strategies.split(",") if s.strip()]
    for s in strategies:
        if s not in ("v1", "v4"):
            raise SystemExit(f"Strategi tidak dikenal: {s} (pakai v1 dan/atau v4)")

    coins = (
        [c.strip().lower() for c in args.coins.split(",") if c.strip()]
        if args.coins else [PRIMARY_COIN]
    )

    buys = parse_list(args.buy_list)
    sells = parse_list(args.sell_list)
    # 0 (atau negatif) pada SL/TP berarti nonaktif -> None di mesin simulasi
    sls = [v if v and v > 0 else None for v in parse_list(args.sl_list)]
    tps = [v if v and v > 0 else None for v in parse_list(args.tp_list)]

    threshold_combos = [
        (b, s) for b in buys for s in sells if b > s
    ]
    skipped = len(buys) * len(sells) - len(threshold_combos)
    n_combos = len(threshold_combos) * len(sls) * len(tps)
    print(
        f"Grid search Recy — strategi: {','.join(strategies)} | "
        f"koin: {','.join(coins)} | {args.days} hari | fee {args.fee:g}"
    )
    print(
        f"Grid: {len(buys)} buy x {len(sells)} sell"
        + (f" (lewati {skipped} pasang buy<=sell)" if skipped else "")
        + f" x {len(sls)} SL x {len(tps)} TP = "
        f"{n_combos} kombinasi/strategi/koin"
    )
    if not threshold_combos:
        raise SystemExit("Tidak ada kombinasi buy/sell yang valid (buy harus > sell)")

    # ------------------------------------------------------------------
    # Data (cache sama dengan run_backtest.py)
    # ------------------------------------------------------------------
    print("\n[1/3] Mengambil data...")
    fng = await get_fng_history(
        days=args.days + 1,
        cache_path=os.path.join(CACHE_DIR, f"fng_{args.days + 1}d.json"),
        force=False,
    )
    print(f"  FNG: {len(fng)} hari")

    data = {}  # coin -> (rows, prices)
    sentiment = {}  # coin -> seri sentimen V4 (butuh jika v4)
    for coin in coins:
        chart = await fetch_prices(coin, HISTORY_DAYS, force=False)
        rows = build_technical_rows(chart["prices"], chart.get("volumes"))
        # evaluasi pada window yang sama dengan run_backtest
        rows = slice_eval_window(rows, args.days)
        if not rows:
            print(f"  [skip] {coin}: data tidak cukup untuk indikator")
            continue
        data[coin] = rows
        print(
            f"  {COIN_LABEL.get(coin, coin)}: {len(rows)} baris "
            f"({_utc_date(rows[0]['timestamp'])} -> {_utc_date(rows[-1]['timestamp'])})"
        )
        if "v4" in strategies:
            v4_series, _coverage = await build_v4_sentiment(
                coin, fng,
                _utc_date(rows[0]["timestamp"]),
                _utc_date(rows[-1]["timestamp"]),
                use_news=not args.skip_news,
            )
            sentiment[coin] = v4_series

    # ------------------------------------------------------------------
    # Grid
    # ------------------------------------------------------------------
    print("\n[2/3] Menjalankan grid...")
    results = []
    for coin, strategy, (buy, sell) in itertools.product(
        data.keys(), strategies, threshold_combos
    ):
        rows = data[coin]
        if strategy == "v1":
            sig = signals_v1(
                rows, buy_threshold=buy, sell_threshold=sell
            )
        else:
            sig = signals_v4(
                rows, sentiment[coin],
                buy_threshold=buy, sell_threshold=sell,
                technical_weight=args.tech_weight,
            )

        start_index = _first_signal_index(sig)
        if start_index is None:
            continue
        prices = [s["price"] for s in sig]

        atr_list = [s.get("atr") for s in sig]
        for sl, tp in itertools.product(sls, tps):
            sim = simulate(
                prices, sig, fee_rate=args.fee,
                stop_loss_pct=sl, take_profit_pct=tp,
                atr=atr_list,
                use_atr_stop_loss=True,
                atr_multiplier=1.5,
            )
            m = compute_metrics(prices, sig, sim, start_index=start_index)
            m.update(
                {
                    "strategy": strategy.upper(),
                    "coin": coin,
                    "buy_threshold": buy,
                    "sell_threshold": sell,
                    "stop_loss_pct": sl,
                    "take_profit_pct": tp,
                    "fee_rate": args.fee,
                    "start_date": _utc_date(sig[start_index]["timestamp"]),
                    "end_date": _utc_date(sig[-1]["timestamp"]),
                }
            )
            results.append(m)

    if not results:
        raise SystemExit("Tidak ada hasil — tidak ada sinyal pada grid ini")

    # ------------------------------------------------------------------
    # Peringkat + artefak
    # ------------------------------------------------------------------
    print("\n[3/3] Menyimpan hasil & mencetak peringkat...")

    by_sharpe = sorted(
        results,
        key=lambda r: (r["sharpe"] is not None, r["sharpe"] or 0.0),
        reverse=True,
    )
    by_excess = sorted(
        results, key=lambda r: r["excess_return_pct"], reverse=True
    )

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OPTIMIZATION_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=RESULT_FIELDS, extrasaction="ignore"
        )
        writer.writeheader()
        for row in results:
            writer.writerow(row)

    print_table("Peringkat Sharpe Ratio", by_sharpe, args.top)
    print_table(
        "Peringkat Excess Return vs Buy & Hold", by_excess, args.top
    )

    best = by_sharpe[0]
    sl_best = best["stop_loss_pct"] or 0.0
    tp_best = best["take_profit_pct"] or 0.0
    print(
        f"\nTerbaik (Sharpe): {best['strategy']} "
        f"{COIN_LABEL.get(best['coin'], best['coin'])} "
        f"buy>={best['buy_threshold']:g} sell<{best['sell_threshold']:g} "
        f"SL {sl_best:.0%} TP {tp_best:.0%} -> "
        f"sharpe {fmt_opt(best['sharpe'])}, "
        f"excess {fmt_opt(best['excess_return_pct'])}%, "
        f"trade {best['n_trades_closed']}"
    )
    print(f"CSV: {OPTIMIZATION_CSV}")
    print(
        "\nPeringatan: semua angka di atas in-sample (window yang sama dengan "
        "backtest) -> risiko overfitting; bukan jaminan performa masa depan."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
