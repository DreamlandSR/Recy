# Laporan Backtesting Recy (V1–V5)

Generated: 2026-10-09T16:45:22+00:00
Periode data: 90 hari terakhir (evaluasi) dari histori 365 hari CoinGecko, harga harian 00:00 UTC.
Koin: BTC, ETH, SOL, BNB, XRP.
Fee transaksi: 0.1% per sisi (eksekusi pada hari berikutnya).
Threshold sinyal: preset **moderasi** (BUY >= 65, SELL < 35).
Risk management: Stop-Loss **3%**, Take-Profit **6%** (eksekusi hari berikutnya setelah terpicu); ATR Stop-Loss dinamis aktif **1.5×ATR14** (level = entri − ATR14 × multiplier); ATR Trailing Stop aktif (level = harga tertinggi sejak entri − ATR14 × multiplier, mengunci profit saat harga naik).
Bobot V4: **70% teknikal + 30% sentimen** (sentimen berita per-koin prioritas, FNG sebagai fallback).

## 1. Metodologi & aturan anti-lookahead

- Sinyal hari *i* **hanya** memakai data yang tersedia di hari *i* (indikator `ta` bersifat kausal/rolling).
- Sinyal hari *i* **dieksekusi di harga hari *i+1*** — tidak ada eksekusi di harga yang sama dengan data sinyal.
- Sentimen selalu **telat ≥ 1 hari**: sinyal hari *i* memakai sentimen terbaru dengan tanggal ≤ *i−1* (FNG maupun berita).
- **Stop-Loss / Take-Profit**: keputusan dihitung dari harga penutupan hari *T* (data ≤ *T*) lalu **dieksekusi di harga hari T+1*** — sama bebas-lookahead-nya dengan aturan sinyal. Pada hari yang sama, risiko (SL/TP) lebih prioritas daripada sinyal SELL. Setiap trade tertutup mencatat `exit_reason` (SIGNAL / STOP_LOSS / ATR_STOP_LOSS / TRAILING_STOP / TAKE_PROFIT), dilaporkan sebagai kolom *SL/ATR/TR/TP*.
- Berita hanya memakai artikel yang terbit **sebelum** hari keputusan (filter `from`/`to` per hari, 00:00–23:59 UTC).
- **Trend Filter Rules (SMA 50/200)**: sinyal BUY diabaikan (diturunkan ke HOLD) bila harga berada di bawah SMA 50 ATAU SMA 200 — mencegah beli di pasar bearish. SELL/HOLD tidak terpengaruh. SMA yang belum terisi di-skip.
- **Volume confirmation**: `volume_ratio = volume / SMA20(volume)` masuk pembobotan technical score — volume di atas rata-rata saat harga naik memberi skor konfirmasi tinggi; volume lemah saat harga naik menurunkan skor (menyaring fake breakout). Tanpa data volume, bobot kembali ke skema lama 0,30/0,40/0,30.
- **Rezim pasar (ADX 14)**: bobot technical score mengikuti rezim — Trending (ADX ≥ 25): trend following dominan (trend 0,40 / momentum 0,35 / volatilitas 0,10 / volume 0,15); Sideways (ADX < 20): oscillator dominan (volatilitas 0,40 / momentum 0,30 / trend 0,15 / volume 0,15); transisi ADX 20–25 memakai bobot netral. **Override mean-reversion**: pada Sideways dengan RSI < 35 (oversold), BUY di bawah SMA 50 diijinkan (syarat SMA 200 tetap mutlak) untuk menangkap harga diskon.
- **ATR Trailing Stop** aktif: level = harga tertinggi sejak entri − ATR14 × multiplier; `highest_since_entry` hanya memakai tutup hari ≤ T, eksekusi T+1 (`exit_reason` = TRAILING_STOP). Bila beberapa stop terpicu hari yang sama, yang paling ketat (level tertinggi) yang menang.
- **Warm-up indikator**: histori diambil 365 hari agar SMA 50/200, ATR 14, ADX 14, dan SMA volume terisi penuh, lalu evaluasi dipotong ke 90 hari terakhir — seluruh hari evaluasi punya indikator lengkap (baris SMA 200 yang belum terisi tetap dipertahankan dengan nilai kosong, tidak menghapus baris).
- Strategi **long-only, all-in**: BUY → buka posisi, SELL → tutup ke cash, HOLD → tahan. Hari tanpa sinyal (`None`) tidak mengeksekusi apa pun.
- Data harga/sentimen di-snapshot ke `backtest_results/cache/*.json` agar hasil dapat direproduksi.
- Akurasi dihitung **hanya dari sinyal BUY/SELL** dengan denominator eksplisit; hari HOLD dilaporkan terpisah.
- Akurasi mengevaluasi **setiap** sinyal BUY/SELL tanpa memedulikan posisi saat itu (sinyal yang dieksekusi maupun yang diabaikan karena posisi sudah sesuai) — karena itu akurasi dan return bisa berbeda arah.

## 2. Ringkasan versi

| Versi | Definisi |
|---|---|
| V1 | Teknikal saja (BUY >= 65, SELL < 35), data asli 90 hari, **fee 0%** |
| V2 | Logika identik V1 + **fee 0,1%/sisi** (baris V1 dengan fee) |
| V3 | Sentimen historis saja (Fear & Greed harian, threshold BUY >= 65, SELL < 35) |
| V4 | `final = 0.70×teknikal + 0.30×sentimen` — sentimen berita per-koin (FinBERT) prioritas, FNG fallback; BUY >= 65, SELL < 35 |
| V5 | Seluruh versi dijalankan pada BTC, ETH, SOL, BNB, XRP |

## 3. Hasil utama — BTC (90 hari data asli)

| Versi | Window | Hari eval | BUY/HOLD/SELL | Akurasi (benar/n) | Return % | Buy&Hold % | Excess % | MaxDD % | Sharpe | Trade | SL/ATR/TR/TP | Win rate % | Fees % |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| V1 — teknikal, fee 0% | 2026-07-12 → 2026-10-09 | 91 | 15 / 76 / 0 | 46.7 (7/15) | -3.32 | 29.94 | -33.26 | 6.55 | -0.83 | 2 | 0 / 0 / 2 / 0 | 0.00 | 0.00 |
| V2 — teknikal + fee 0,1% | 2026-07-12 → 2026-10-09 | 91 | 15 / 76 / 0 | 46.7 (7/15) | -3.71 | 29.94 | -33.64 | 6.83 | -0.94 | 2 | 0 / 0 / 2 / 0 | 0.00 | 0.40 |
| V3 — sentimen FNG, fee 0% | 2026-07-12 → 2026-10-09 | 91 | 39 / 14 / 38 | 46.8 (36/77) | 10.87 | 29.94 | -19.07 | 5.59 | 1.77 | 6 | 0 / 1 / 3 / 2 | 66.67 | 0.00 |
| V3 — sentimen FNG, fee 0,1% | 2026-07-12 → 2026-10-09 | 91 | 39 / 14 / 38 | 46.8 (36/77) | 9.54 | 29.94 | -20.39 | 5.78 | 1.58 | 6 | 0 / 1 / 3 / 2 | 66.67 | 1.26 |
| V4 — teknikal + sentimen, fee 0% | 2026-07-12 → 2026-10-09 | 91 | 10 / 81 / 0 | 30.0 (3/10) | -3.67 | 29.94 | -33.61 | 6.55 | -0.83 | 3 | 0 / 0 / 3 / 0 | 0.00 | 0.00 |
| V4 — teknikal + sentimen, fee 0,1% | 2026-07-12 → 2026-10-09 | 91 | 10 / 81 / 0 | 30.0 (3/10) | -4.25 | 29.94 | -34.19 | 6.83 | -0.97 | 3 | 0 / 0 / 3 / 0 | 0.00 | 0.59 |

Catatan:
- **V2 = baris V1 dengan fee** (logika sinyal identik, yang berbeda hanya biaya transaksi) — selisihnya adalah *fee drag*.
- `Fees %` = akumulasi fee terhadap modal awal.
- *Buy & hold* dihitung dari hari pertama yang punya sinyal.
- Sharpe diannualisasi (√365), dihitung dari return harian equity.

## 4. V5 — perbandingan antar-koin (fee 0,1%/sisi)

| Koin | Versi | Hari eval | Akurasi (benar/n) | Return % | Buy&Hold % | MaxDD % | Sharpe | Trade | SL/ATR/TR/TP | Win rate % |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | V1 | 91 | 46.7 (7/15) | -3.71 | 29.94 | 6.83 | -0.94 | 2 | 0 / 0 / 2 / 0 | 0.00 |
| BTC | V3 | 91 | 46.8 (36/77) | 9.54 | 29.94 | 5.78 | 1.58 | 6 | 0 / 1 / 3 / 2 | 66.67 |
| BTC | V4 | 91 | 30.0 (3/10) | -4.25 | 29.94 | 6.83 | -0.97 | 3 | 0 / 0 / 3 / 0 | 0.00 |
| ETH | V1 | 91 | 52.9 (9/17) | -6.87 | 39.19 | 10.24 | -1.39 | 4 | 0 / 2 / 2 / 0 | 50.00 |
| ETH | V3 | 91 | 46.8 (36/77) | 7.81 | 39.19 | 11.29 | 1.22 | 5 | 0 / 0 / 4 / 1 | 80.00 |
| ETH | V4 | 91 | 41.2 (7/17) | -6.00 | 39.19 | 10.24 | -1.05 | 4 | 0 / 1 / 3 / 0 | 50.00 |
| SOL | V1 | 91 | 60.0 (12/20) | -12.21 | 42.83 | 14.99 | -2.04 | 3 | 0 / 0 / 3 / 0 | 0.00 |
| SOL | V3 | 91 | 53.2 (41/77) | 3.67 | 42.83 | 13.31 | 0.58 | 8 | 2 / 0 / 3 / 3 | 37.50 |
| SOL | V4 | 91 | 52.2 (12/23) | -5.54 | 42.83 | 16.36 | -0.57 | 4 | 0 / 0 / 3 / 1 | 25.00 |
| BNB | V1 | 91 | 56.2 (9/16) | 18.16 | 28.62 | 3.91 | 3.01 | 4 | 0 / 0 / 2 / 2 | 50.00 |
| BNB | V3 | 91 | 50.6 (39/77) | 11.43 | 28.62 | 8.22 | 1.79 | 7 | 0 / 1 / 4 / 2 | 28.57 |
| BNB | V4 | 91 | 52.4 (11/21) | -2.89 | 28.62 | 12.79 | -0.39 | 6 | 0 / 2 / 3 / 1 | 16.67 |
| XRP | V1 | 91 | 37.5 (3/8) | -13.01 | 25.95 | 13.01 | -3.64 | 2 | 1 / 1 / 0 / 0 | 0.00 |
| XRP | V3 | 91 | 49.4 (38/77) | 1.04 | 25.95 | 13.09 | 0.30 | 8 | 1 / 0 / 4 / 3 | 37.50 |
| XRP | V4 | 91 | 46.7 (7/15) | -15.63 | 25.95 | 18.70 | -3.53 | 3 | 1 / 1 / 1 / 0 | 0.00 |

- Baris **V2** tiap koin = baris **V1** (fee 0,1%), karena V2 hanya menambahkan fee pada logika V1.
- Detail per hari: `backtest_results/details/v{1,3,4}_<koin>.csv`.

## 5. Validasi sentimen — FNG vs GNews+FinBERT (window 30 hari sama)

Window: 2026-09-10 → 2026-10-09.

- Hari diminta: **30**, berhasil diambil: **29**, hari dengan artikel: **29**.
- Hari yang dipakai bersama (FNG ∩ berita): **29**
- **Korelasi Pearson antara Fear & Greed dan sentimen berita (FinBERT): 0.24**

| Varian | Window | Hari eval | BUY/HOLD/SELL | Akurasi (benar/n) | Return % | Buy&Hold % | MaxDD % | Sharpe | Trade | Win rate % |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| V3-FNG | 2026-09-10 → 2026-10-09 | 31 | 22 / 9 / 0 | 40.9 (9/22) | 1.62 | 5.88 | 5.65 | 0.77 | 3 | 33.33 |
| V3-Berita | 2026-09-11 → 2026-10-09 | 30 | 5 / 20 / 5 | 20.0 (2/10) | 2.37 | 8.27 | 5.65 | 1.13 | 2 | 50.00 |
| V4-FNG | 2026-09-10 → 2026-10-09 | 31 | 13 / 18 / 0 | 46.1 (6/13) | -3.39 | 5.88 | 5.65 | -2.58 | 1 | 0.00 |
| V4-Berita | 2026-09-11 → 2026-10-09 | 30 | 7 / 23 / 0 | 28.6 (2/7) | -3.39 | 8.27 | 5.65 | -2.58 | 1 | 0.00 |

Jika korelasi positif dan arah metrik keduanya sejajar, sentimen FNG layak dipakai sebagai proksi sentimen 90 hari (arsip GNews free plan hanya ~30 hari).

**Interpretasi jujur:** korelasi terukur 0.24 tergolong *positif tetapi lemah*.
Artinya Fear & Greed dan sentimen berita FinBERT **tidak saling menggantikan** — keduanya menangkap dimensi yang berbeda (FNG: perilaku pasar; berita: narasi per-koin).
Bukti nyata pada window yang sama: V3-FNG menghasilkan 22/9/0 sinyal (B/H/S) dengan 3 trade tertutup, sedangkan V3-Berita 5/20/5 dengan 2 trade tertutup — sentimen berita jauh lebih responsif berubah arah.
Rekomendasi — **sudah diimplementasikan pada V4 run ini**: sentimen berita per-koin (FinBERT) diprioritaskan per tanggal, FNG hanya sebagai fallback (hari di luar arsip berita); ulangi validasi ini bila arsip berita diperluas.

## 6. Keterbatasan

- Fear & Greed Index bersifat **market-wide**, bukan per-koin; sentimen berita per-koin hanya tersedia ~30 hari terakhir (limitasi arsip GNews free plan).
- Threshold (preset *moderasi*: BUY >= 65, SELL < 35) dan bobot V4 (70%/30%) kini **configurable**; angka di laporan ini adalah konfigurasi run ini (nilai baseline lama: 70/30 dan 0.60/0.40, tersedia via `--thresholds baseline --tech-weight 0.60`).
- Grid search (`optimize_backtest.py`) mencari parameter terbaik pada window yang sama (**in-sample**) — berisiko overfitting; walk-forward validation diperlukan sebelum dipakai di produksi.
- SL/TP **dan ATR SL** dievaluasi dari **harga penutupan harian** (bukan intraday); karena eksekusi di harga hari berikutnya, *gap* yang menembus batas bisa tereksekusi lebih buruk dari level SL/TP itu sendiri.
- ATR memakai proxy close-to-close (data `market_chart` CoinGecko tidak punya OHLC: high=low=close), jadi ATR14 adalah volatilitas perubahan harga harian, bukan range intraday. ADX juga dari close saja (high/low disintesis ε=1e-4 tanpa menambah informasi) — nilainya mendekati ADX OHLC sejauh arah harian sebanding.
- Warm-up indikator (SMA 50/200, ATR 14, ADX 14, volume SMA 20) disediakan oleh histori 365 hari, sehingga seluruh 90 hari evaluasi punya indikator terisi (lihat kolom *Hari eval*).
- Backtest harian long-only tanpa ukuran posisi, slippage, atau pajak; fee hanya 0,1% per sisi.
- Data tunggal per periode (tanpa walk-forward/optimasi in-sample); hasil tidak menjamin performa masa depan.
- Bukan nasihat investasi.

## 7. Artefak

- `backtest_results/metrics.csv` — semua run (versi × koin × fee)
- `backtest_results/v5_matrix.csv` — matriks V5 pada fee 0,1%
- `backtest_results/details/*.csv` — detail per hari per run
- `backtest_results/optimization.csv` — hasil grid search (dibuat oleh `optimize_backtest.py` bila dijalankan)
- `backtest_results/cache/*.json` — snapshot data mentah
