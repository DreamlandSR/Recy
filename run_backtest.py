"""Runner backtest Recy — V1 sampai V5.

Menghasilkan artefak di ``backtest_results/``:
  report.md                     -> laporan perbandingan semua versi
  metrics.csv                   -> semua run (versi x koin x skenario fee)
  v5_matrix.csv                 -> matriks V5 (fee 0,1%/sisi)
  details/<version>_<coin>.csv  -> detail per hari tiap run
  cache/*.json                  -> snapshot data mentah (reproduktif)

Pemakaian:
  .venv/Scripts/python run_backtest.py
  .venv/Scripts/python run_backtest.py --versions v1,v2,v3,v4 --coins bitcoin
  .venv/Scripts/python run_backtest.py --force-refetch --skip-news
"""

import argparse
import asyncio
import csv
import json
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

import httpx

# Konsol Windows (cp1252) tidak bisa menampilkan karakter seperti →;
# paksa stdout UTF-8 agar log tidak gagal.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.services.backtest_engine import compute_metrics, simulate
from app.services.backtest_service import (
    THRESHOLD_PRESETS,
    _utc_date,
    build_technical_rows,
    merge_sentiment_series,
    signals_v1,
    signals_v3,
    signals_v4,
)
from app.services.crypto_service import get_coin_history
from app.services.sentiment_history_service import (
    get_daily_news_sentiment,
    get_fng_history,
)

PRIMARY_COIN = "bitcoin"
V5_COINS = ["bitcoin", "ethereum", "solana", "binancecoin", "ripple"]
COIN_LABEL = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "binancecoin": "BNB",
    "ripple": "XRP",
}

FEE_RATE = 0.001  # 0,1% per sisi (taker)
FEES = [0.0, FEE_RATE]
DEFAULT_DAYS = 90          # window evaluasi (hari terakhir)
HISTORY_DAYS = 365         # histori indikator (SMA 50/200 + ATR warm-up)
NEWS_WINDOW_DAYS = 30

OUT_DIR = "backtest_results"
DETAILS_DIR = os.path.join(OUT_DIR, "details")
CACHE_DIR = os.path.join(OUT_DIR, "cache")


def log(message: str = ""):
    print(message, flush=True)


# =====================================================================
# Data
# =====================================================================

async def fetch_prices(coin: str, days: int, force: bool = False) -> dict:
    """Harga + volume harian CoinGecko dengan cache + retry backoff.

    Return {"prices": [...], "volumes": [...]} (parallel array).
    Cache yang belum punya `volumes` (format lama) dianggap basi dan
    di-refetch otomatis.
    """
    cache_path = os.path.join(CACHE_DIR, f"prices_{coin}_{days}d.json")
    if not force and os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as fh:
            cached = json.load(fh)
        prices = cached.get("prices")
        volumes = cached.get("volumes")
        if prices and volumes and len(volumes) == len(prices):
            log(f"  [cache] {coin}: {len(prices)} titik harga (+volume)")
            return {"prices": prices, "volumes": volumes}
        log(f"  [cache] {coin}: tanpa volume/format lama -> refetch")

    last_error = None
    for attempt in range(4):
        # 2 percobaan pertama memakai API key; percobaan berikutnya
        # fallback ke endpoint publik CoinGecko (tanpa key).
        use_key = attempt < 2
        try:
            history = await get_coin_history(coin, days=days, with_api_key=use_key)
            prices = history["prices"]
            volumes = history.get("total_volumes") or []
            if len(volumes) != len(prices):
                # Panjang beda -> jangan simpan volume cacat; skor volume
                # akan netral sampai fetch berikutnya berhasil.
                log(f"  [warn] {coin}: volume tidak sepanjang harga "
                    f"({len(volumes)} vs {len(prices)}) -> tanpa volume")
                volumes = []
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "coin": coin,
                        "days": days,
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "prices": prices,
                        "volumes": volumes,
                    },
                    fh,
                )
            log(f"  [fetch] {coin}: {len(prices)} titik harga ({days} hari)")
            return {"prices": prices, "volumes": volumes}
        except httpx.HTTPStatusError as exc:
            last_error = exc
            status = exc.response.status_code
            retryable = status in (401, 429, 500, 502, 503, 504)
            if retryable and attempt < 3:
                wait = 15 * (attempt + 1)
                log(f"  [http {status}] {coin}: tunggu {wait}s lalu coba lagi "
                    f"({'tanpa key' if not use_key else 'dengan key'})...")
                await asyncio.sleep(wait)
                continue
            raise
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt < 3:
                await asyncio.sleep(10)
                continue
            raise

    raise RuntimeError(f"Gagal mengambil harga {coin}: {last_error}")


# =====================================================================
# Evaluasi satu konfigurasi sinyal x skenario fee
# =====================================================================

def slice_eval_window(rows: list, days: int) -> list:
    """Potong rows menjadi `days` hari terakhir (window evaluasi).

    Histori lebih panjang (HISTORY_DAYS) dipakai untuk warm-up indikator
    (SMA 50/200, ATR, volume) sehingga SELURUH hari evaluasi sudah punya
    indikator terisi tanpa membuang baris apa pun di dalam window.
    """
    if not rows or not days or days <= 0:
        return rows
    last = date.fromisoformat(_utc_date(rows[-1]["timestamp"]))
    start = last - timedelta(days=days - 1)
    sliced = [
        r for r in rows
        if date.fromisoformat(_utc_date(r["timestamp"])) >= start
    ]
    return sliced or rows


def _first_signal_index(signals: list):
    for i, s in enumerate(signals):
        if s is not None and s["signal"] is not None:
            return i
    return None


def evaluate(
    version: str,
    coin: str,
    signals: list,
    fees: list,
    details_path: str = None,
    stop_loss_pct: float = None,
    take_profit_pct: float = None,
    use_atr_stop_loss: bool = True,
    atr_multiplier: float = 1.5,
    use_trailing_stop: bool = True,
) -> list:
    """Jalankan simulasi tiap skenario fee + hitung metrik.

    `stop_loss_pct` / `take_profit_pct` diteruskan ke mesin simulasi
    (None = nonaktif). ATR SL & ATR Trailing Stop dinamis memakai field
    `atr` per sinyal (None = inert). Return list of dict metrics (satu per
    skenario fee).
    """
    start_index = _first_signal_index(signals)
    if start_index is None:
        log(f"  [skip] {version}/{coin}: tidak ada sinyal sama sekali")
        return []

    prices = [s["price"] for s in signals]
    atr = [s.get("atr") for s in signals]

    sims = {}
    runs = []
    for fee in fees:
        sim = simulate(
            prices,
            signals,
            fee_rate=fee,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            atr=atr,
            use_atr_stop_loss=use_atr_stop_loss,
            atr_multiplier=atr_multiplier,
            use_trailing_stop=use_trailing_stop,
        )
        sims[fee] = sim
        metrics = compute_metrics(prices, signals, sim, start_index=start_index)
        metrics.update(
            {
                "version": version,
                "coin": coin,
                "fee_rate": fee,
                "fee_pct": round(fee * 100, 3),
                "start_date": _utc_date(signals[start_index]["timestamp"]),
                "end_date": _utc_date(signals[-1]["timestamp"]),
            }
        )
        runs.append(metrics)

    if details_path:
        _write_details(details_path, signals, sims)

    return runs


def _write_details(path: str, signals: list, sims: dict):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fee_keys = sorted(sims.keys())
    header = [
        "date",
        "price",
        "technical_score",
        "sentiment_score",
        "final_score",
        "signal",
        "next_day_return_pct",
        "position_after_execution",
    ] + [f"equity_fee_{fee:g}".replace(".", "_") for fee in fee_keys]

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for i, sig in enumerate(signals):
            date_iso = _utc_date(sig["timestamp"])
            if i < len(signals) - 1:
                nxt = signals[i + 1]["price"]
                next_ret = round((nxt / sig["price"] - 1.0) * 100, 4)
            else:
                next_ret = ""
            writer.writerow(
                [
                    date_iso,
                    sig["price"],
                    sig["technical_score"],
                    sig["sentiment_score"],
                    sig["final_score"],
                    sig["signal"],
                    next_ret,
                    sims[fee_keys[0]]["positions"][i],
                ]
                + [round(sims[fee]["equity_curve"][i], 8) for fee in fee_keys]
            )


# =====================================================================
# Util laporan
# =====================================================================

def f2(value, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}{suffix}"


def pearson(xs: list, ys: list):
    if len(xs) < 3:
        return None
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def signal_distribution(run: dict) -> str:
    return (
        f"{run['n_buy_signals']} / {run['n_hold_signals']} / "
        f"{run['n_sell_signals']}"
    )


def find_run(runs: list, version: str, coin: str, fee: float):
    for run in runs:
        if (
            run["version"] == version
            and run["coin"] == coin
            and abs(run["fee_rate"] - fee) < 1e-12
        ):
            return run
    return None


# =====================================================================
# Validasi sentimen 30 hari (FNG vs GNews + FinBERT)
# =====================================================================

async def run_news_validation(
    rows: list,
    runs: list,
    days: int,
    buy_threshold: float = 70,
    sell_threshold: float = 30,
    stop_loss_pct: float = None,
    take_profit_pct: float = None,
    tech_weight: float = 0.60,
    use_atr_stop_loss: bool = True,
    atr_multiplier: float = 1.5,
    use_trailing_stop: bool = True,
) -> dict:
    """Bandingkan sentimen FNG vs GNews+FinBERT pada window 30 hari yang sama."""
    if not rows:
        return {}

    last_date = _utc_date(rows[-1]["timestamp"])
    first_date = _utc_date(rows[0]["timestamp"])
    news_start = max(
        date.fromisoformat(first_date),
        date.fromisoformat(last_date) - timedelta(days=NEWS_WINDOW_DAYS - 1),
    )

    log(f"\n[validasi] mengambil berita {PRIMARY_COIN} {news_start} -> {last_date} ...")
    news_payload = await get_daily_news_sentiment(
        PRIMARY_COIN, news_start, date.fromisoformat(last_date), CACHE_DIR
    )
    news_series = news_payload["series"]
    coverage = news_payload["coverage"]
    log(
        f"  hari diminta {coverage['days_requested']}, "
        f"berhasil diambil {coverage['days_fetched']}, "
        f"punya artikel {coverage['days_with_articles']}"
    )

    if not news_series:
        log("  [validasi] tidak ada sentimen berita -> dilewati")
        return {"skipped": True, "coverage": coverage}

    start_iso = news_start.isoformat()

    def slice_signals(signals: list) -> list:
        for i, sig in enumerate(signals):
            if _utc_date(sig["timestamp"]) >= start_iso:
                return signals[i:]
        return []

    fng_series = get_cached_fng(days)

    news_runs = []
    for label, builder, series in [
        ("V3-FNG", signals_v3, fng_series),
        ("V3-Berita", signals_v3, news_series),
        ("V4-FNG", signals_v4, fng_series),
        ("V4-Berita", signals_v4, news_series),
    ]:
        kwargs = {
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
        }
        if label.startswith("V4"):
            kwargs["technical_weight"] = tech_weight
        full = builder(rows, series, **kwargs)
        sliced = slice_signals(full)
        produced = evaluate(
            label,
            PRIMARY_COIN,
            sliced,
            [FEE_RATE],
            details_path=os.path.join(DETAILS_DIR, f"{label}_{PRIMARY_COIN}.csv")
            if sliced
            else None,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            use_atr_stop_loss=use_atr_stop_loss,
            atr_multiplier=atr_multiplier,
            use_trailing_stop=use_trailing_stop,
        )
        news_runs.extend(produced)

    # Korelasi harian FNG vs sentimen berita (tanggal yang sama)
    common = sorted(set(fng_series) & set(news_series))
    xs = [fng_series[d]["score"] for d in common]
    ys = [news_series[d]["score"] for d in common]
    corr = pearson(xs, ys)

    return {
        "skipped": False,
        "start": start_iso,
        "end": last_date,
        "runs": news_runs,
        "coverage": coverage,
        "correlation": round(corr, 3) if corr is not None else None,
        "n_common_days": len(common),
        "fng_scores": {d: fng_series[d]["score"] for d in common},
        "news_scores": {d: news_series[d]["score"] for d in common},
    }


_fng_cache = {}


def get_cached_fng(days: int) -> dict:
    return _fng_cache[days]


async def build_v4_sentiment(
    coin: str,
    fng: dict,
    first_date: str,
    last_date: str,
    use_news: bool = True,
) -> tuple:
    """Seri sentimen untuk V4 per koin: berita per-koin (FinBERT/GNews)
    PRIORITAS pada tanggal yang tersedia; FNG makro hanya sebagai
    fallback (hari di luar arsip berita ~30 hari / saat fetch gagal).

    Return (series, coverage).
    """
    if not use_news:
        return fng, None

    news_start = max(
        date.fromisoformat(first_date),
        date.fromisoformat(last_date)
        - timedelta(days=NEWS_WINDOW_DAYS - 1),
    )
    try:
        payload = await get_daily_news_sentiment(
            coin, news_start, date.fromisoformat(last_date), CACHE_DIR
        )
    except Exception as exc:  # noqa: BLE001 - kuota/jaringan -> fallback FNG
        log(f"  [news] {coin}: gagal ({type(exc).__name__}: {exc}) "
            f"-> pakai FNG sebagai fallback")
        return fng, None

    coverage = payload.get("coverage")
    if coverage and coverage.get("quota_exhausted"):
        log(f"  [news] {coin}: kuota GNews habis di "
            f"{coverage.get('days_fetched')}/{coverage.get('days_requested')} "
            f"hari -> hari sisanya pakai FNG (cache per hari, bisa dilanjut "
            f"pada run berikutnya)")

    news_series = payload.get("series") or {}
    if not news_series:
        log(f"  [news] {coin}: tidak ada sentimen berita -> FNG fallback")
        return fng, coverage

    merged = merge_sentiment_series(news_series, fng)
    log(f"  [news] {coin}: {len(news_series)} hari sentimen berita "
        f"-> prioritas atas FNG ({len(fng)} hari)")
    return merged, coverage


# =====================================================================
# Laporan Markdown
# =====================================================================

def build_report(
    runs: list,
    coins: list,
    days: int,
    validation: dict,
    versions: list,
    generated_at: str,
    config: dict = None,
) -> str:
    cfg = {
        "thresholds_preset": "baseline",
        "buy_threshold": 70,
        "sell_threshold": 30,
        "stop_loss_pct": None,
        "take_profit_pct": None,
        "tech_weight": 0.60,
        "use_atr_stop_loss": True,
        "atr_multiplier": 1.5,
        "use_trailing_stop": True,
    }
    if config:
        cfg.update(config)

    sl_txt = (
        f"{cfg['stop_loss_pct']:.0%}"
        if cfg["stop_loss_pct"] else "nonaktif"
    )
    tp_txt = (
        f"{cfg['take_profit_pct']:.0%}"
        if cfg["take_profit_pct"] else "nonaktif"
    )
    thr_txt = (
        f"BUY >= {cfg['buy_threshold']:g}, SELL < {cfg['sell_threshold']:g}"
    )
    atr_txt = (
        f"aktif **{cfg.get('atr_multiplier', 1.5):g}×ATR14**"
        if cfg.get("use_atr_stop_loss") else "nonaktif"
    )
    trail_txt = "aktif" if cfg.get("use_trailing_stop") else "nonaktif"

    lines = []
    add = lines.append

    add("# Laporan Backtesting Recy (V1–V5)")
    add("")
    add(f"Generated: {generated_at}")
    add(f"Periode data: {days} hari terakhir (evaluasi) dari histori "
        f"{HISTORY_DAYS} hari CoinGecko, harga harian 00:00 UTC.")
    add(f"Koin: {', '.join(COIN_LABEL.get(c, c) for c in coins)}.")
    add(f"Fee transaksi: {FEE_RATE * 100:.1f}% per sisi (eksekusi pada hari berikutnya).")
    add(f"Threshold sinyal: preset **{cfg['thresholds_preset']}** ({thr_txt}).")
    add(f"Risk management: Stop-Loss **{sl_txt}**, Take-Profit **{tp_txt}** "
        f"(eksekusi hari berikutnya setelah terpicu); ATR Stop-Loss dinamis "
        f"{atr_txt} (level = entri − ATR14 × multiplier); ATR Trailing Stop "
        f"{trail_txt} (level = harga tertinggi sejak entri − ATR14 × "
        f"multiplier, mengunci profit saat harga naik).")
    add(f"Bobot V4: **{cfg['tech_weight']:.0%} teknikal + "
        f"{1 - cfg['tech_weight']:.0%} sentimen** (sentimen berita per-koin "
        f"prioritas, FNG sebagai fallback).")
    add("")

    add("## 1. Metodologi & aturan anti-lookahead")
    add("")
    add("- Sinyal hari *i* **hanya** memakai data yang tersedia di hari *i* "
        "(indikator `ta` bersifat kausal/rolling).")
    add("- Sinyal hari *i* **dieksekusi di harga hari *i+1*** — tidak ada "
        "eksekusi di harga yang sama dengan data sinyal.")
    add("- Sentimen selalu **telat ≥ 1 hari**: sinyal hari *i* memakai "
        "sentimen terbaru dengan tanggal ≤ *i−1* (FNG maupun berita).")
    add("- **Stop-Loss / Take-Profit**: keputusan dihitung dari harga "
        "penutupan hari *T* (data ≤ *T*) lalu **dieksekusi di harga hari "
        "T+1*** — sama bebas-lookahead-nya dengan aturan sinyal. Pada hari "
        "yang sama, risiko (SL/TP) lebih prioritas daripada sinyal SELL. "
        "Setiap trade tertutup mencatat `exit_reason` (SIGNAL / STOP_LOSS / "
        "ATR_STOP_LOSS / TRAILING_STOP / TAKE_PROFIT), dilaporkan sebagai "
        "kolom *SL/ATR/TR/TP*.")
    add("- Berita hanya memakai artikel yang terbit **sebelum** hari keputusan "
        "(filter `from`/`to` per hari, 00:00–23:59 UTC).")
    add("- **Trend Filter Rules (SMA 50/200)**: sinyal BUY diabaikan "
        "(diturunkan ke HOLD) bila harga berada di bawah SMA 50 ATAU SMA 200 — "
        "mencegah beli di pasar bearish. SELL/HOLD tidak terpengaruh. SMA yang "
        "belum terisi di-skip.")
    add("- **Volume confirmation**: `volume_ratio = volume / SMA20(volume)` "
        "masuk pembobotan technical score — volume di atas rata-rata saat harga "
        "naik memberi skor konfirmasi tinggi; volume lemah saat harga naik "
        "menurunkan skor (menyaring fake breakout). Tanpa data volume, bobot "
        "kembali ke skema lama 0,30/0,40/0,30.")
    add(f"- **Rezim pasar (ADX 14)**: bobot technical score mengikuti rezim "
        f"— Trending (ADX ≥ 25): trend following dominan (trend 0,40 / "
        f"momentum 0,35 / volatilitas 0,10 / volume 0,15); Sideways "
        f"(ADX < 20): oscillator dominan (volatilitas 0,40 / momentum 0,30 / "
        f"trend 0,15 / volume 0,15); transisi ADX 20–25 memakai bobot netral. "
        f"**Override mean-reversion**: pada Sideways dengan RSI < 35 "
        f"(oversold), BUY di bawah SMA 50 diijinkan (syarat SMA 200 tetap "
        f"mutlak) untuk menangkap harga diskon.")
    add(f"- **ATR Trailing Stop** {trail_txt}: level = harga tertinggi "
        f"sejak entri − ATR14 × multiplier; `highest_since_entry` hanya "
        f"memakai tutup hari ≤ T, eksekusi T+1 (`exit_reason` = "
        f"TRAILING_STOP). Bila beberapa stop terpicu hari yang sama, yang "
        f"paling ketat (level tertinggi) yang menang.")
    add(f"- **Warm-up indikator**: histori diambil {HISTORY_DAYS} hari agar "
        f"SMA 50/200, ATR 14, ADX 14, dan SMA volume terisi penuh, lalu evaluasi "
        f"dipotong ke {days} hari terakhir — seluruh hari evaluasi punya "
        f"indikator lengkap (baris SMA 200 yang belum terisi tetap dipertahankan "
        f"dengan nilai kosong, tidak menghapus baris).")
    add("- Strategi **long-only, all-in**: BUY → buka posisi, SELL → tutup ke "
        "cash, HOLD → tahan. Hari tanpa sinyal (`None`) tidak mengeksekusi apa pun.")
    add("- Data harga/sentimen di-snapshot ke `backtest_results/cache/*.json` "
        "agar hasil dapat direproduksi.")
    add("- Akurasi dihitung **hanya dari sinyal BUY/SELL** dengan denominator "
        "eksplisit; hari HOLD dilaporkan terpisah.")
    add("- Akurasi mengevaluasi **setiap** sinyal BUY/SELL tanpa memedulikan "
        "posisi saat itu (sinyal yang dieksekusi maupun yang diabaikan karena "
        "posisi sudah sesuai) — karena itu akurasi dan return bisa berbeda arah.")
    add("")

    add("## 2. Ringkasan versi")
    add("")
    add("| Versi | Definisi |")
    add("|---|---|")
    add(f"| V1 | Teknikal saja ({thr_txt}), data asli 90 hari, **fee 0%** |")
    add("| V2 | Logika identik V1 + **fee 0,1%/sisi** (baris V1 dengan fee) |")
    add(f"| V3 | Sentimen historis saja (Fear & Greed harian, threshold {thr_txt}) |")
    add(f"| V4 | `final = {cfg['tech_weight']:.2f}×teknikal + {1 - cfg['tech_weight']:.2f}×sentimen` — sentimen berita per-koin (FinBERT) prioritas, FNG fallback; {thr_txt} |")
    add("| V5 | Seluruh versi dijalankan pada BTC, ETH, SOL, BNB, XRP |")
    add("")

    # ---------------- Tabel utama BTC ----------------
    add(f"## 3. Hasil utama — BTC ({days} hari data asli)")
    add("")
    add("| Versi | Window | Hari eval | BUY/HOLD/SELL | Akurasi (benar/n) | Return % | Buy&Hold % | Excess % | MaxDD % | Sharpe | Trade | SL/ATR/TR/TP | Win rate % | Fees % |")
    add("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

    rows_spec = []
    if "v1" in versions or "v2" in versions:
        rows_spec.append(
            ("V1 — teknikal, fee 0%", "V1", 0.0)
        )
        rows_spec.append(
            ("V2 — teknikal + fee 0,1%", "V1", FEE_RATE)
        )
    if "v3" in versions:
        rows_spec.append(("V3 — sentimen FNG, fee 0%", "V3", 0.0))
        rows_spec.append(("V3 — sentimen FNG, fee 0,1%", "V3", FEE_RATE))
    if "v4" in versions:
        rows_spec.append(("V4 — teknikal + sentimen, fee 0%", "V4", 0.0))
        rows_spec.append(("V4 — teknikal + sentimen, fee 0,1%", "V4", FEE_RATE))

    for label, version, fee in rows_spec:
        run = find_run(runs, version, PRIMARY_COIN, fee)
        if not run:
            continue
        acc = "n/a" if run["signal_accuracy_pct"] is None else (
            f"{run['signal_accuracy_pct']:.1f} ({run['n_correct']}/{run['n_directional_signals']})"
        )
        add(
            f"| {label} "
            f"| {run['start_date']} → {run['end_date']} "
            f"| {run['n_eval_days']} "
            f"| {signal_distribution(run)} "
            f"| {acc} "
            f"| {f2(run['total_return_pct'])} "
            f"| {f2(run['buy_hold_return_pct'])} "
            f"| {f2(run['excess_return_pct'])} "
            f"| {f2(run['max_drawdown_pct'])} "
            f"| {f2(run['sharpe'])} "
            f"| {run['n_trades_closed']} "
            f"| {run.get('n_stop_loss_triggered', 0)} / "
            f"{run.get('n_atr_stop_loss_triggered', 0)} / "
            f"{run.get('n_trailing_stop_triggered', 0)} / "
            f"{run.get('n_take_profit_triggered', 0)} "
            f"| {f2(run['win_rate_pct'])} "
            f"| {f2(run['fees_paid_pct'])} |"
        )
    add("")
    add("Catatan:")
    add("- **V2 = baris V1 dengan fee** (logika sinyal identik, yang berbeda "
        "hanya biaya transaksi) — selisihnya adalah *fee drag*.")
    add("- `Fees %` = akumulasi fee terhadap modal awal.")
    add("- *Buy & hold* dihitung dari hari pertama yang punya sinyal.")
    add("- Sharpe diannualisasi (√365), dihitung dari return harian equity.")
    add("")

    # ---------------- V5 ----------------
    if "v5" in versions and len(coins) > 1:
        add("## 4. V5 — perbandingan antar-koin (fee 0,1%/sisi)")
        add("")
        add("| Koin | Versi | Hari eval | Akurasi (benar/n) | Return % | Buy&Hold % | MaxDD % | Sharpe | Trade | SL/ATR/TR/TP | Win rate % |")
        add("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for coin in coins:
            for version, label in [("V1", "V1"), ("V3", "V3"), ("V4", "V4")]:
                if version == "V3" and "v3" not in versions:
                    continue
                if version == "V4" and "v4" not in versions:
                    continue
                run = find_run(runs, version, coin, FEE_RATE)
                if not run:
                    continue
                acc = "n/a" if run["signal_accuracy_pct"] is None else (
                    f"{run['signal_accuracy_pct']:.1f} ({run['n_correct']}/{run['n_directional_signals']})"
                )
                add(
                    f"| {COIN_LABEL.get(coin, coin)} "
                    f"| {label} "
                    f"| {run['n_eval_days']} "
                    f"| {acc} "
                    f"| {f2(run['total_return_pct'])} "
                    f"| {f2(run['buy_hold_return_pct'])} "
                    f"| {f2(run['max_drawdown_pct'])} "
                    f"| {f2(run['sharpe'])} "
                    f"| {run['n_trades_closed']} "
                    f"| {run.get('n_stop_loss_triggered', 0)} / "
            f"{run.get('n_atr_stop_loss_triggered', 0)} / "
            f"{run.get('n_trailing_stop_triggered', 0)} / "
            f"{run.get('n_take_profit_triggered', 0)} "
                    f"| {f2(run['win_rate_pct'])} |"
                )
        add("")
        add("- Baris **V2** tiap koin = baris **V1** (fee 0,1%), karena V2 "
            "hanya menambahkan fee pada logika V1.")
        add("- Detail per hari: `backtest_results/details/v{1,3,4}_<koin>.csv`.")
        add("")

    # ---------------- Validasi sentimen ----------------
    add("## 5. Validasi sentimen — FNG vs GNews+FinBERT (window 30 hari sama)")
    add("")
    if not validation or validation.get("skipped"):
        add("_Validasi sentimen berita tidak dijalankan / tidak ada data berita "
            "pada window ini (lihat log konsol)._")
        add("")
    else:
        cov = validation["coverage"]
        add(f"Window: {validation['start']} → {validation['end']}.")
        add("")
        add(f"- Hari diminta: **{cov['days_requested']}**, berhasil diambil: "
            f"**{cov['days_fetched']}**, hari dengan artikel: "
            f"**{cov['days_with_articles']}**.")
        add(f"- Hari yang dipakai bersama (FNG ∩ berita): "
            f"**{validation['n_common_days']}**")
        add(f"- **Korelasi Pearson antara Fear & Greed dan sentimen berita "
            f"(FinBERT): {validation['correlation']}**")
        add("")
        add("| Varian | Window | Hari eval | BUY/HOLD/SELL | Akurasi (benar/n) | Return % | Buy&Hold % | MaxDD % | Sharpe | Trade | Win rate % |")
        add("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for label in ["V3-FNG", "V3-Berita", "V4-FNG", "V4-Berita"]:
            run = find_run(validation["runs"], label, PRIMARY_COIN, FEE_RATE)
            if not run:
                continue
            acc = "n/a" if run["signal_accuracy_pct"] is None else (
                f"{run['signal_accuracy_pct']:.1f} ({run['n_correct']}/{run['n_directional_signals']})"
            )
            add(
                f"| {label} "
                f"| {run['start_date']} → {run['end_date']} "
                f"| {run['n_eval_days']} "
                f"| {signal_distribution(run)} "
                f"| {acc} "
                f"| {f2(run['total_return_pct'])} "
                f"| {f2(run['buy_hold_return_pct'])} "
                f"| {f2(run['max_drawdown_pct'])} "
                f"| {f2(run['sharpe'])} "
                f"| {run['n_trades_closed']} "
                f"| {f2(run['win_rate_pct'])} |"
            )
        add("")
        add("Jika korelasi positif dan arah metrik keduanya sejajar, sentimen "
            "FNG layak dipakai sebagai proksi sentimen 90 hari (arsip GNews "
            "free plan hanya ~30 hari).")
        add("")
        # Interpretasi berdasarkan angka yang benar-benar terukur
        corr = validation.get("correlation")
        if corr is None:
            strength = "tidak terdefinisi"
        elif abs(corr) < 0.3:
            strength = "lemah"
        elif abs(corr) < 0.6:
            strength = "sedang"
        else:
            strength = "kuat"
        direction = "positif" if (corr is not None and corr > 0) else "negatif"
        add(f"**Interpretasi jujur:** korelasi terukur {corr} tergolong "
            f"*{direction} tetapi {strength}*.")
        add("Artinya Fear & Greed dan sentimen berita FinBERT **tidak saling "
            "menggantikan** — keduanya menangkap dimensi yang berbeda "
            "(FNG: perilaku pasar; berita: narasi per-koin).")
        v3f = find_run(validation["runs"], "V3-FNG", PRIMARY_COIN, FEE_RATE)
        v3b = find_run(validation["runs"], "V3-Berita", PRIMARY_COIN, FEE_RATE)
        if v3f and v3b:
            add(f"Bukti nyata pada window yang sama: V3-FNG menghasilkan "
                f"{v3f['n_buy_signals']}/{v3f['n_hold_signals']}/{v3f['n_sell_signals']} "
                f"sinyal (B/H/S) dengan {v3f['n_trades_closed']} trade tertutup, "
                f"sedangkan V3-Berita "
                f"{v3b['n_buy_signals']}/{v3b['n_hold_signals']}/{v3b['n_sell_signals']} "
                f"dengan {v3b['n_trades_closed']} trade tertutup — sentimen berita "
                "jauh lebih responsif berubah arah.")
        add("Rekomendasi — **sudah diimplementasikan pada V4 run ini**: sentimen "
            "berita per-koin (FinBERT) diprioritaskan per tanggal, FNG hanya "
            "sebagai fallback (hari di luar arsip berita); ulangi validasi ini "
            "bila arsip berita diperluas.")
        add("")

    add("## 6. Keterbatasan")
    add("")
    add("- Fear & Greed Index bersifat **market-wide**, bukan per-koin; sentimen "
        "berita per-koin hanya tersedia ~30 hari terakhir (limitasi arsip GNews free plan).")
    add(f"- Threshold (preset *{cfg['thresholds_preset']}*: {thr_txt}) dan "
        f"bobot V4 ({cfg['tech_weight']:.0%}/{1 - cfg['tech_weight']:.0%}) "
        f"kini **configurable**; angka di laporan ini adalah konfigurasi run "
        f"ini (nilai baseline lama: 70/30 dan 0.60/0.40, tersedia via "
        f"`--thresholds baseline --tech-weight 0.60`).")
    add("- Grid search (`optimize_backtest.py`) mencari parameter terbaik pada "
        "window yang sama (**in-sample**) — berisiko overfitting; "
        "walk-forward validation diperlukan sebelum dipakai di produksi.")
    add("- SL/TP **dan ATR SL** dievaluasi dari **harga penutupan harian** "
        "(bukan intraday); karena eksekusi di harga hari berikutnya, *gap* "
        "yang menembus batas bisa tereksekusi lebih buruk dari level SL/TP "
        "itu sendiri.")
    add(f"- ATR memakai proxy close-to-close (data `market_chart` CoinGecko "
        f"tidak punya OHLC: high=low=close), jadi ATR14 adalah volatilitas "
        f"perubahan harga harian, bukan range intraday. ADX juga dari close "
        f"saja (high/low disintesis ε=1e-4 tanpa menambah informasi) — "
        f"nilainya mendekati ADX OHLC sejauh arah harian sebanding.")
    add(f"- Warm-up indikator (SMA 50/200, ATR 14, ADX 14, volume SMA 20) disediakan "
        f"oleh histori {HISTORY_DAYS} hari, sehingga seluruh {days} hari "
        "evaluasi punya indikator terisi (lihat kolom *Hari eval*).")
    add("- Backtest harian long-only tanpa ukuran posisi, slippage, atau pajak; "
        "fee hanya 0,1% per sisi.")
    add("- Data tunggal per periode (tanpa walk-forward/optimasi in-sample); "
        "hasil tidak menjamin performa masa depan.")
    add("- Bukan nasihat investasi.")
    add("")

    add("## 7. Artefak")
    add("")
    add("- `backtest_results/metrics.csv` — semua run (versi × koin × fee)")
    add("- `backtest_results/v5_matrix.csv` — matriks V5 pada fee 0,1%")
    add("- `backtest_results/details/*.csv` — detail per hari per run")
    add("- `backtest_results/optimization.csv` — hasil grid search "
        "(dibuat oleh `optimize_backtest.py` bila dijalankan)")
    add("- `backtest_results/cache/*.json` — snapshot data mentah")
    add("")

    return "\n".join(lines)


# =====================================================================
# Main
# =====================================================================

async def main():
    parser = argparse.ArgumentParser(description="Backtest Recy V1-V5")
    parser.add_argument(
        "--versions", default="v1,v2,v3,v4,v5",
        help="daftar versi, mis. v1,v2,v3,v4,v5",
    )
    parser.add_argument(
        "--coins", default="",
        help="koin tambahan (default: BTC saja; v5 menambah ETH,SOL,BNB,XRP)",
    )
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument(
        "--thresholds", default="moderasi", choices=sorted(THRESHOLD_PRESETS),
        help="preset threshold sinyal (default: moderasi = BUY 65 / SELL 35; "
             "baseline = BUY 70 / SELL 30)",
    )
    parser.add_argument(
        "--buy-threshold", type=float, default=None,
        help="override threshold BUY (mis. 60); mengalahkan preset",
    )
    parser.add_argument(
        "--sell-threshold", type=float, default=None,
        help="override threshold SELL (mis. 40); mengalahkan preset",
    )
    parser.add_argument(
        "--stop-loss", type=float, default=0.03,
        help="Stop-Loss sebagai fraksi harga (0.03 = 3%%; 0 = nonaktif)",
    )
    parser.add_argument(
        "--take-profit", type=float, default=0.06,
        help="Take-Profit sebagai fraksi harga (0.06 = 6%%; 0 = nonaktif)",
    )
    parser.add_argument(
        "--tech-weight", type=float, default=0.70,
        help="bobot teknikal pada V4 (0.70 = 70%% teknikal + 30%% sentimen; "
             "baseline 0.60)",
    )
    parser.add_argument(
        "--atr-sl", action=argparse.BooleanOptionalAction, default=True,
        help="Stop-Loss ATR dinamis 1,5xATR14 (default aktif; "
             "--no-atr-sl mematikan)",
    )
    parser.add_argument(
        "--atr-multiplier", type=float, default=1.5,
        help="pengali ATR untuk Stop-Loss dinamis (default 1.5)",
    )
    parser.add_argument(
        "--trailing-stop", action=argparse.BooleanOptionalAction, default=True,
        help="ATR Trailing Stop untuk mengunci profit (default aktif; "
             "--no-trailing-stop mematikan)",
    )
    parser.add_argument("--skip-news", action="store_true",
                        help="lewati pengambilan/validasi berita")
    parser.add_argument("--force-refetch", action="store_true",
                        help="abaikan cache data")
    args = parser.parse_args()

    versions = [v.strip().lower() for v in args.versions.split(",") if v.strip()]

    # Resolusi konfigurasi strategi (preset + override manual)
    buy_threshold, sell_threshold = THRESHOLD_PRESETS[args.thresholds]
    if args.buy_threshold is not None:
        buy_threshold = args.buy_threshold
    if args.sell_threshold is not None:
        sell_threshold = args.sell_threshold
    stop_loss_pct = args.stop_loss if args.stop_loss and args.stop_loss > 0 else None
    take_profit_pct = (
        args.take_profit if args.take_profit and args.take_profit > 0 else None
    )
    tech_weight = args.tech_weight
    use_atr_stop_loss = args.atr_sl
    atr_multiplier = args.atr_multiplier
    use_trailing_stop = args.trailing_stop

    coins = []
    if args.coins:
        coins = [c.strip().lower() for c in args.coins.split(",") if c.strip()]
    else:
        coins = [PRIMARY_COIN]
    if "v5" in versions:
        for coin in V5_COINS:
            if coin not in coins:
                coins.append(coin)

    os.makedirs(DETAILS_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)

    started = datetime.now(timezone.utc)
    log(f"Backtest Recy — versi: {','.join(versions)} | koin: {','.join(coins)} | {args.days} hari")
    log(
        f"Konfigurasi: threshold [{args.thresholds}] BUY>={buy_threshold:g} "
        f"SELL<{sell_threshold:g} | SL "
        f"{f'{stop_loss_pct:.0%}' if stop_loss_pct else 'nonaktif'} / TP "
        f"{f'{take_profit_pct:.0%}' if take_profit_pct else 'nonaktif'} "
        f"| ATR SL "
        + (
            f"aktif {atr_multiplier:g}xATR14"
            if use_atr_stop_loss else "nonaktif"
        )
        + " | Trailing "
        + (f"aktif {atr_multiplier:g}xATR14" if use_trailing_stop else "nonaktif")
        + f" | V4 bobot teknikal {tech_weight:.0%}"
    )
    fetch_days = max(args.days, HISTORY_DAYS)

    # 1. Harga
    log(f"\n[1/5] Mengambil data harga ({fetch_days} hari histori, "
        f"evaluasi {args.days} hari terakhir)...")
    prices_by_coin = {}
    for coin in coins:
        prices_by_coin[coin] = await fetch_prices(
            coin, fetch_days, force=args.force_refetch
        )
        if coin != coins[-1]:
            await asyncio.sleep(3)  # hindari rate limit CoinGecko

    # 2. Fear & Greed
    log("\n[2/5] Mengambil Fear & Greed Index...")
    # +1 hari: lag anti-lookahead butuh sentimen hari sebelum eval pertama.
    fng = await get_fng_history(
        days=args.days + 1,
        cache_path=os.path.join(CACHE_DIR, f"fng_{args.days + 1}d.json"),
        force=args.force_refetch,
    )
    _fng_cache[args.days] = fng
    log(f"  {len(fng)} hari sentimen FNG ({min(fng)} → {max(fng)})")

    # 3. Sinyal + evaluasi
    log("\n[3/5] Menjalankan backtest per versi/koin...")
    runs = []
    news_coverage = {}
    for coin in coins:
        rows = build_technical_rows(
            prices_by_coin[coin]["prices"],
            prices_by_coin[coin]["volumes"],
        )
        rows = slice_eval_window(rows, args.days)
        if not rows:
            log(f"  [skip] {coin}: data tidak cukup untuk indikator")
            continue
        log(f"  {COIN_LABEL.get(coin, coin)}: {len(rows)} baris evaluasi "
            f"({_utc_date(rows[0]['timestamp'])} → {_utc_date(rows[-1]['timestamp'])})")

        first_date = _utc_date(rows[0]["timestamp"])
        last_date = _utc_date(rows[-1]["timestamp"])
        v4_kwargs = {
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
            "technical_weight": tech_weight,
        }

        if "v1" in versions or "v2" in versions:
            s1 = signals_v1(
                rows, buy_threshold=buy_threshold,
                sell_threshold=sell_threshold,
            )
            runs.extend(evaluate(
                "V1", coin, s1, FEES,
                os.path.join(DETAILS_DIR, f"v1_{coin}.csv"),
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                use_atr_stop_loss=use_atr_stop_loss,
                atr_multiplier=atr_multiplier,
                use_trailing_stop=use_trailing_stop,
            ))
        if "v3" in versions:
            s3 = signals_v3(
                rows, fng, buy_threshold=buy_threshold,
                sell_threshold=sell_threshold,
            )
            runs.extend(evaluate(
                "V3", coin, s3, FEES,
                os.path.join(DETAILS_DIR, f"v3_{coin}.csv"),
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                use_atr_stop_loss=use_atr_stop_loss,
                atr_multiplier=atr_multiplier,
                use_trailing_stop=use_trailing_stop,
            ))
        if "v4" in versions:
            # Prioritas sentimen berita per-koin (FinBERT); FNG fallback.
            v4_sentiment, coverage = await build_v4_sentiment(
                coin, fng, first_date, last_date,
                use_news=not args.skip_news,
            )
            news_coverage[coin] = coverage
            s4 = signals_v4(rows, v4_sentiment, **v4_kwargs)
            runs.extend(evaluate(
                "V4", coin, s4, FEES,
                os.path.join(DETAILS_DIR, f"v4_{coin}.csv"),
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                use_atr_stop_loss=use_atr_stop_loss,
                atr_multiplier=atr_multiplier,
                use_trailing_stop=use_trailing_stop,
            ))

    # 4. Validasi sentimen 30 hari
    validation = {}
    if not args.skip_news and ("v3" in versions or "v4" in versions):
        log("\n[4/5] Validasi sentimen (berita FinBERT)...")
        primary_hist = prices_by_coin.get(PRIMARY_COIN) or {
            "prices": [], "volumes": []
        }
        primary_rows = slice_eval_window(
            build_technical_rows(
                primary_hist["prices"], primary_hist.get("volumes")
            ),
            args.days,
        )
        validation = await run_news_validation(
            primary_rows, runs, args.days,
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            tech_weight=tech_weight,
            use_atr_stop_loss=use_atr_stop_loss,
            atr_multiplier=atr_multiplier,
        )
    else:
        log("\n[4/5] Validasi berita dilewati (--skip-news).")

    # 5. Artefak
    log("\n[5/5] Menulis laporan & CSV...")
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    metric_fields = [
        "version", "coin", "fee_rate", "fee_pct", "start_date", "end_date",
        "n_days", "n_eval_days", "n_buy_signals", "n_hold_signals",
        "n_sell_signals", "n_no_signal_days", "n_directional_signals",
        "n_correct", "signal_accuracy_pct", "hold_avg_next_return_pct",
        "total_return_pct", "buy_hold_return_pct", "excess_return_pct",
        "max_drawdown_pct", "sharpe", "n_executions", "fees_paid_pct",
        "n_trades_closed", "n_stop_loss_triggered", "n_atr_stop_loss_triggered",
        "n_trailing_stop_triggered", "n_take_profit_triggered",
        "win_rate_pct", "avg_trade_pct", "profit_factor",
        "open_trade_unrealized_pct",
    ]
    with open(os.path.join(OUT_DIR, "metrics.csv"), "w", newline="",
              encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=metric_fields, extrasaction="ignore")
        writer.writeheader()
        for run in runs:
            writer.writerow(run)

    with open(os.path.join(OUT_DIR, "v5_matrix.csv"), "w", newline="",
              encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=metric_fields, extrasaction="ignore")
        writer.writeheader()
        for run in runs:
            if abs(run["fee_rate"] - FEE_RATE) < 1e-12 and run["coin"] in V5_COINS:
                writer.writerow(run)

    report = build_report(
        runs, coins, args.days, validation, versions, generated_at,
        config={
            "thresholds_preset": args.thresholds,
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "tech_weight": tech_weight,
            "use_atr_stop_loss": use_atr_stop_loss,
            "atr_multiplier": atr_multiplier,
            "use_trailing_stop": use_trailing_stop,
        },
    )
    report_path = os.path.join(OUT_DIR, "report.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(report)

    # Ringkasan konsol
    log("\n=== Ringkasan (BTC) ===")
    for label, version, fee in [
        ("V1 fee 0%   ", "V1", 0.0),
        ("V2 fee 0,1% ", "V1", FEE_RATE),
        ("V3 FNG fee 0,1%", "V3", FEE_RATE),
        ("V4 fee 0,1% ", "V4", FEE_RATE),
    ]:
        run = find_run(runs, version, PRIMARY_COIN, fee)
        if not run:
            continue
        acc = "n/a" if run["signal_accuracy_pct"] is None else \
            f"{run['signal_accuracy_pct']}% ({run['n_correct']}/{run['n_directional_signals']})"
        log(
            f"  {label}: return {run['total_return_pct']}% | "
            f"buy&hold {run['buy_hold_return_pct']}% | "
            f"maxDD {run['max_drawdown_pct']}% | akurasi {acc} | "
            f"trade {run['n_trades_closed']} "
            f"(SL {run.get('n_stop_loss_triggered', 0)} / "
            f"ATR {run.get('n_atr_stop_loss_triggered', 0)} / "
            f"TR {run.get('n_trailing_stop_triggered', 0)} / "
            f"TP {run.get('n_take_profit_triggered', 0)}) | "
            f"win rate {run['win_rate_pct'] if run['win_rate_pct'] is not None else 'n/a'}"
        )

    log(f"\nLaporan: {report_path}")
    log(f"Selesai dalam {(datetime.now(timezone.utc) - started).seconds} detik")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
