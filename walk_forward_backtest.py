"""Walk-Forward Validation Recy — bukti strategi tidak overfit (Phase 3).

Skema:
  In-Sample (Latih)  : `--is-days` hari pertama (default 180 = ~6 bulan)
                       -> grid search threshold BUY/SELL x multiplier ATR,
                          dipilih berdasarkan Sharpe (tie-break: excess return).
  Out-of-Sample (Uji): `--oos-days` hari berikutnya (default 90 = ~3 bulan)
                       -> parameter TERBAIK hasil latih dibekukan dan
                          diterapkan tanpa perubahan apa pun.

Semua indikator dihitung pada histori penuh (365 hari, cache yang sama dengan
run_backtest.py) lalu dipecah berdasarkan tanggal — indikator `ta` bersifat
kausal/rolling, sehingga baris In-Sample maupun Out-of-Sample hanya memakai
data <= hari keputusan; tidak ada data masa depan yang bocor ke parameter
(nyala dipilih murni dari periode latih).

Konfigurasi risiko identik dengan run_backtest: fee 0,1%/sisi, SL 3%, TP 6%,
ATR SL 1,5xATR14 (multiplier jadi variabel grid), ATR Trailing Stop aktif,
eksekusi sinyal hari i pada harga hari i+1.

Output: backtest_results/walk_forward_report.md

Pemakaian:
  .venv/Scripts/python walk_forward_backtest.py
  .venv/Scripts/python walk_forward_backtest.py --coin solana --is-days 180 --oos-days 90
  .venv/Scripts/python walk_forward_backtest.py --atr-list 1.0,1.5,2.0,2.5 --top 10
"""

import argparse
import asyncio
import itertools
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.services.backtest_engine import compute_metrics, simulate
from app.services.backtest_service import (
    _utc_date,
    build_technical_rows,
    signals_v1,
)
from run_backtest import (
    CACHE_DIR,
    COIN_LABEL,
    FEE_RATE,
    HISTORY_DAYS,
    OUT_DIR,
    _first_signal_index,
    fetch_prices,
    log,
    slice_eval_window,
)

REPORT_PATH = os.path.join(OUT_DIR, "walk_forward_report.md")

# Konfigurasi risiko (identik run_backtest)
STOP_LOSS_PCT = 0.03
TAKE_PROFIT_PCT = 0.06
USE_ATR_STOP_LOSS = True
USE_TRAILING_STOP = True

DEFAULT_BUY_LIST = "55,60,65,70,75"
DEFAULT_SELL_LIST = "25,30,35,40,45"
DEFAULT_ATR_LIST = "1.0,1.5,2.0,2.5"


def parse_list(text: str, cast=float) -> list:
    return [cast(x.strip()) for x in text.split(",") if x.strip()]


def evaluate_params(rows: list, buy: float, sell: float, atr_mult: float,
                    fee: float):
    """Bangun sinyal V1 + simulasi pada rows; return metrics atau None."""
    sig = signals_v1(rows, buy_threshold=buy, sell_threshold=sell)
    start = _first_signal_index(sig)
    if start is None:
        return None
    prices = [s["price"] for s in sig]
    atr = [s.get("atr") for s in sig]
    sim = simulate(
        prices, sig, fee_rate=fee,
        stop_loss_pct=STOP_LOSS_PCT,
        take_profit_pct=TAKE_PROFIT_PCT,
        atr=atr,
        use_atr_stop_loss=USE_ATR_STOP_LOSS,
        atr_multiplier=atr_mult,
        use_trailing_stop=USE_TRAILING_STOP,
    )
    m = compute_metrics(prices, sig, sim, start_index=start)
    m["start_date"] = _utc_date(sig[start]["timestamp"])
    m["end_date"] = _utc_date(sig[-1]["timestamp"])
    return m


def f2(value, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:.2f}{suffix}"


def metric_row(label: str, m: dict) -> str:
    return (
        f"| {label} | {m['start_date']} → {m['end_date']} "
        f"| {m['n_eval_days']} "
        f"| {m['n_buy_signals']} / {m['n_hold_signals']} / {m['n_sell_signals']} "
        f"| {f2(m['total_return_pct'])} | {f2(m['buy_hold_return_pct'])} "
        f"| {f2(m['excess_return_pct'])} | {f2(m['max_drawdown_pct'])} "
        f"| {f2(m['sharpe'])} | {m['n_trades_closed']} "
        f"| {m['n_stop_loss_triggered']} / {m['n_atr_stop_loss_triggered']} "
        f"/ {m['n_trailing_stop_triggered']} / {m['n_take_profit_triggered']} "
        f"| {f2(m['win_rate_pct'])} |"
    )


async def main():
    parser = argparse.ArgumentParser(
        description="Walk-Forward Validation Recy (IS latih -> OOS uji)"
    )
    parser.add_argument("--coin", default="bitcoin")
    parser.add_argument("--is-days", type=int, default=180,
                        help="panjang window latih dalam hari (default 180)")
    parser.add_argument("--oos-days", type=int, default=90,
                        help="panjang window uji dalam hari (default 90)")
    parser.add_argument("--fee", type=float, default=FEE_RATE)
    parser.add_argument("--buy-list", default=DEFAULT_BUY_LIST)
    parser.add_argument("--sell-list", default=DEFAULT_SELL_LIST)
    parser.add_argument("--atr-list", default=DEFAULT_ATR_LIST,
                        help="kandidat multiplier ATR (default 1.0,1.5,2.0,2.5)")
    parser.add_argument("--top", type=int, default=10,
                        help="jumlah baris teratas tabel In-Sample (default 10)")
    parser.add_argument("--force-refetch", action="store_true")
    args = parser.parse_args()

    buys = parse_list(args.buy_list)
    sells = parse_list(args.sell_list)
    atr_mults = parse_list(args.atr_list)
    combos = [(b, s) for b in buys for s in sells if b > s]
    n_combos = len(combos) * len(atr_mults)
    if not combos:
        raise SystemExit("Tidak ada kombinasi buy/sell valid (buy harus > sell)")

    coin = args.coin.strip().lower()
    started = datetime.now(timezone.utc)
    label = COIN_LABEL.get(coin, coin)

    log(f"Walk-Forward Validation — {label} | latih {args.is_days} hari -> "
        f"uji {args.oos_days} hari | fee {args.fee:g}")
    log(f"Grid: {len(combos)} threshold x {len(atr_mults)} multiplier ATR "
        f"= {n_combos} kombinasi")

    # ------------------------------------------------------------------
    # Data (cache sama dengan run_backtest; indikator dihitung sekali pada
    # histori penuh -> kausal, lalu dipecah berdasarkan tanggal)
    # ------------------------------------------------------------------
    log("\n[1/3] Mengambil data harga...")
    chart = await fetch_prices(
        coin, HISTORY_DAYS, force=args.force_refetch
    )
    rows_full = build_technical_rows(chart["prices"], chart.get("volumes"))
    if not rows_full:
        raise SystemExit(f"{label}: data tidak cukup untuk indikator")

    oos_rows = slice_eval_window(rows_full, args.oos_days)
    oos_start = _utc_date(oos_rows[0]["timestamp"])
    combined = slice_eval_window(rows_full, args.is_days + args.oos_days)
    is_rows = [r for r in combined if _utc_date(r["timestamp"]) < oos_start]

    log(f"  {label}: {len(rows_full)} baris indikator (histori {HISTORY_DAYS} hari)")
    log(f"  In-Sample  : {len(is_rows)} baris "
        f"({_utc_date(is_rows[0]['timestamp'])} → "
        f"{_utc_date(is_rows[-1]['timestamp'])})")
    log(f"  Out-of-Sample: {len(oos_rows)} baris "
        f"({oos_start} → {_utc_date(oos_rows[-1]['timestamp'])})")
    if len(is_rows) < 30 or len(oos_rows) < 10:
        raise SystemExit("Window terlalu pendek untuk indikator/evaluasi")

    # ------------------------------------------------------------------
    # In-Sample: grid search (pilihan parameter HANYA dari data latih)
    # ------------------------------------------------------------------
    log(f"\n[2/3] Grid search In-Sample ({n_combos} kombinasi)...")
    results = []
    for (buy, sell), mult in itertools.product(combos, atr_mults):
        m = evaluate_params(is_rows, buy, sell, mult, args.fee)
        if m is None:
            continue
        m["buy_threshold"] = buy
        m["sell_threshold"] = sell
        m["atr_multiplier"] = mult
        results.append(m)

    if not results:
        raise SystemExit("Tidak ada sinyal pada window latih")

    results.sort(
        key=lambda r: (
            r["sharpe"] is not None,
            r["sharpe"] if r["sharpe"] is not None else -99.0,
            r["excess_return_pct"],
        ),
        reverse=True,
    )
    best = results[0]

    # ------------------------------------------------------------------
    # Out-of-Sample: parameter beku, tanpa penyesuaian
    # ------------------------------------------------------------------
    log(f"\n[3/3] Uji Out-of-Sample dengan parameter terbaik "
        f"(BUY>={best['buy_threshold']:g}, SELL<{best['sell_threshold']:g}, "
        f"ATR x{best['atr_multiplier']:g})...")
    oos_best = evaluate_params(
        oos_rows, best["buy_threshold"], best["sell_threshold"],
        best["atr_multiplier"], args.fee,
    )
    # Konteks: parameter default produksi (65/35, 1.5x) pada window yang sama
    oos_default = evaluate_params(oos_rows, 65, 35, 1.5, args.fee)
    if oos_best is None:
        raise SystemExit("Parameter terbaik tidak menghasilkan sinyal OOS")

    # ------------------------------------------------------------------
    # Laporan
    # ------------------------------------------------------------------
    log("\nMenulis laporan...")
    os.makedirs(OUT_DIR, exist_ok=True)
    lines = []
    add = lines.append

    dd_delta = oos_best["max_drawdown_pct"] - best["max_drawdown_pct"]
    sh_is = best["sharpe"] if best["sharpe"] is not None else 0.0
    sh_oos = (
        oos_best["sharpe"] if oos_best["sharpe"] is not None else 0.0
    )
    sh_delta = sh_oos - sh_is

    add("# Walk-Forward Validation Recy")
    add("")
    add(f"Generated: {started.isoformat(timespec='seconds')}")
    add(f"Koin: {label}. Fee: {args.fee * 100:.1f}% per sisi. "
        f"Risiko: SL {STOP_LOSS_PCT:.0%}, TP {TAKE_PROFIT_PCT:.0%}, "
        f"ATR SL & ATR Trailing Stop aktif (multiplier = variabel grid).")
    add("")
    add("## 1. Desain eksperimen & anti-lookahead")
    add("")
    add(f"- **In-Sample (latih)**: {len(is_rows)} hari "
        f"({_utc_date(is_rows[0]['timestamp'])} → "
        f"{_utc_date(is_rows[-1]['timestamp'])}) — grid "
        f"{len(combos)} threshold x {len(atr_mults)} multiplier ATR = "
        f"{n_combos} kombinasi, dipilih berdasarkan **Sharpe** "
        f"(tie-break: excess return).")
    add(f"- **Out-of-Sample (uji)**: {len(oos_rows)} hari "
        f"({oos_start} → {_utc_date(oos_rows[-1]['timestamp'])}) — parameter "
        f"terbaik **dibekukan** (threshold + multiplier) tanpa penyesuaian.")
    add("- Parameter dipilih murni dari periode latih; tidak ada data OOS "
        "yang dipakai saat seleksi (bukan lookahead).")
    add("- Sinyal hari *i* hanya memakai data <= hari *i* dan dieksekusi di "
        "harga hari *i+1*; SL/TP/ATR/trailing dievaluasi dari tutup hari "
        "*T* lalu dieksekusi hari *T+1*.")
    add("- Indikator dihitung sekali pada histori penuh (365 hari, cache "
        "sama dengan run_backtest) lalu dipecah per tanggal — semua "
        "indikator `ta` kausal/rolling, jadi baris OOS tidak pernah "
        "memengaruhi baris IS dan sebaliknya.")
    add("- *Buy & hold* dihitung dari hari pertama yang punya sinyal pada "
        "masing-masing window.")
    add("")

    add("## 2. Hasil In-Sample — peringkat grid (top "
        f"{min(args.top, len(results))})")
    add("")
    add("| # | BUY | SELL | ATR× | Return % | B&H % | Excess % | MaxDD % "
        "| Sharpe | Trade | SL/ATR/TR/TP | Win % |")
    add("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|")
    for i, r in enumerate(results[: args.top], start=1):
        add(
            f"| {i} | {r['buy_threshold']:g} | {r['sell_threshold']:g} "
            f"| {r['atr_multiplier']:g} | {f2(r['total_return_pct'])} "
            f"| {f2(r['buy_hold_return_pct'])} "
            f"| {f2(r['excess_return_pct'])} | {f2(r['max_drawdown_pct'])} "
            f"| {f2(r['sharpe'])} | {r['n_trades_closed']} "
            f"| {r['n_stop_loss_triggered']} / "
            f"{r['n_atr_stop_loss_triggered']} / "
            f"{r['n_trailing_stop_triggered']} / "
            f"{r['n_take_profit_triggered']} | {f2(r['win_rate_pct'])} |"
        )
    add("")
    add(f"**Parameter terbaik (latih)**: BUY >= {best['buy_threshold']:g}, "
        f"SELL < {best['sell_threshold']:g}, ATR multiplier "
        f"{best['atr_multiplier']:g}.")
    add("")

    add("## 3. In-Sample vs Out-of-Sample (parameter terbaik dibekukan)")
    add("")
    add("| Set | Window | Hari eval | B/H/S | Return % | B&H % | Excess % "
        "| MaxDD % | Sharpe | Trade | SL/ATR/TR/TP | Win % |")
    add("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|")
    add(metric_row("In-Sample (latih)", best))
    add(metric_row("Out-of-Sample (uji)", oos_best))
    if oos_default:
        add(metric_row("OOS — parameter default (65/35, ATR 1,5×)", oos_default))
    add("")

    add("## 4. Analisis degradasi (jujur)")
    add("")
    sharpe_line = (
        f"- Sharpe: IS **{f2(best['sharpe'])}** -> OOS "
        f"**{f2(oos_best['sharpe'])}** (delta {sh_delta:+.2f}"
    )
    if sh_is > 0 and sh_oos > 0:
        sharpe_line += f"; OOS menyimpan {sh_oos / sh_is * 100:.0f}% Sharpe IS"
    elif sh_is > 0 and sh_oos <= 0:
        sharpe_line += "; **Sharpe berbalik negatif pada OOS**"
    add(sharpe_line + ").")
    add(f"- Max Drawdown: IS **{f2(best['max_drawdown_pct'])}%** -> OOS "
        f"**{f2(oos_best['max_drawdown_pct'])}%** (delta {dd_delta:+.2f} poin).")
    add(f"- Return: IS **{f2(best['total_return_pct'])}%** -> OOS "
        f"**{f2(oos_best['total_return_pct'])}%** (buy & hold OOS "
        f"{f2(oos_best['buy_hold_return_pct'])}%).")
    add("")
    if sh_oos < sh_is and sh_delta < -0.5:
        add("**Interpretasi**: performa Out-of-Sample turun sejalan ekspektasi "
            "seleksi in-sample (parameter memang dipilih karena beruntung pada "
            "periode latih). Selama Sharpe OOS masih positif dan degradasi "
            "lebih kecil dari selisih acak, strategi **layak lanjut ke tahap "
            "forward-testing**; bila Sharpe OOS negatif, parameter hasil grid "
            "tidak generalizable dan strategi perlu peninjauan.")
    elif sh_oos > 0:
        add("**Interpretasi**: parameter terbaik mempertahankan Sharpe positif "
            "pada data yang tidak pernah dipakai saat seleksi — bukti awal "
            "bahwa aturan sinyal bukan sekadar overfit pada window latih "
            "(bukan jaminan performa masa depan).")
    else:
        add("**Interpretasi**: Sharpe OOS <= 0 — kombinasi parameter hasil "
            "grid tidak bertahan di luar data latih; jangan pakai parameter "
            "ini di produksi tanpa validasi tambahan.")
    add("")

    add("## 5. Keterbatasan")
    add("")
    add("- Hanya **satu** split latih/uji (bukan walk-forward bergulir "
        "banyak window) — tambahkan beberapa window untuk estimasi lebih "
        "stabil.")
    add("- Window latih 6 bulan / uji 3 bulan pada satu koin; hasil bisa "
        "berbeda pada koin/periode lain (regime pasar berubah).")
    add("- Grid threshold dan multiplier ATR dikombinasikan dengan SL/TP "
        "tetap (3%/6%) — interaksi parameter lain tidak dieksplorasi di sini.")
    add("- Slippage, pajak, dan ukuran posisi tidak dimodelkan; fee hanya "
        f"{args.fee * 100:.1f}% per sisi.")
    add("- Bukan nasihat investasi.")
    add("")

    add("## 6. Artefak")
    add("")
    add("- `backtest_results/walk_forward_report.md` — laporan ini")
    add("- `backtest_results/cache/prices_*.json` — snapshot data (reproduktif)")
    add("")

    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    log(f"\nParameter terbaik (IS): BUY>={best['buy_threshold']:g} "
        f"SELL<{best['sell_threshold']:g} ATR x{best['atr_multiplier']:g}")
    log(f"  IS  : sharpe {f2(best['sharpe'])} | return "
        f"{f2(best['total_return_pct'])}% | maxDD "
        f"{f2(best['max_drawdown_pct'])}% | trade {best['n_trades_closed']}")
    log(f"  OOS : sharpe {f2(oos_best['sharpe'])} | return "
        f"{f2(oos_best['total_return_pct'])}% | maxDD "
        f"{f2(oos_best['max_drawdown_pct'])}% | trade "
        f"{oos_best['n_trades_closed']}")
    log(f"\nLaporan: {REPORT_PATH}")
    log(f"Selesai dalam {(datetime.now(timezone.utc) - started).seconds} detik")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
