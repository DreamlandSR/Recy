# Walk-Forward Validation Recy

Generated: 2026-10-09T16:43:10+00:00
Koin: BTC. Fee: 0.1% per sisi. Risiko: SL 3%, TP 6%, ATR SL & ATR Trailing Stop aktif (multiplier = variabel grid).

## 1. Desain eksperimen & anti-lookahead

- **In-Sample (latih)**: 180 hari (2026-01-13 → 2026-07-11) — grid 25 threshold x 4 multiplier ATR = 100 kombinasi, dipilih berdasarkan **Sharpe** (tie-break: excess return).
- **Out-of-Sample (uji)**: 91 hari (2026-07-12 → 2026-10-09) — parameter terbaik **dibekukan** (threshold + multiplier) tanpa penyesuaian.
- Parameter dipilih murni dari periode latih; tidak ada data OOS yang dipakai saat seleksi (bukan lookahead).
- Sinyal hari *i* hanya memakai data <= hari *i* dan dieksekusi di harga hari *i+1*; SL/TP/ATR/trailing dievaluasi dari tutup hari *T* lalu dieksekusi hari *T+1*.
- Indikator dihitung sekali pada histori penuh (365 hari, cache sama dengan run_backtest) lalu dipecah per tanggal — semua indikator `ta` kausal/rolling, jadi baris OOS tidak pernah memengaruhi baris IS dan sebaliknya.
- *Buy & hold* dihitung dari hari pertama yang punya sinyal pada masing-masing window.

## 2. Hasil In-Sample — peringkat grid (top 10)

| # | BUY | SELL | ATR× | Return % | B&H % | Excess % | MaxDD % | Sharpe | Trade | SL/ATR/TR/TP | Win % |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| 1 | 60 | 45 | 2.5 | 1.36 | -29.70 | 31.06 | 7.01 | 0.25 | 6 | 0 / 0 / 2 / 1 | 66.67 |
| 2 | 60 | 40 | 2.5 | 1.02 | -29.70 | 30.72 | 7.32 | 0.21 | 6 | 0 / 0 / 2 / 1 | 66.67 |
| 3 | 70 | 25 | 1 | 0.00 | -29.70 | 29.70 | 0.00 | 0.00 | 0 | 0 / 0 / 0 / 0 | n/a |
| 4 | 70 | 25 | 1.5 | 0.00 | -29.70 | 29.70 | 0.00 | 0.00 | 0 | 0 / 0 / 0 / 0 | n/a |
| 5 | 70 | 25 | 2 | 0.00 | -29.70 | 29.70 | 0.00 | 0.00 | 0 | 0 / 0 / 0 / 0 | n/a |
| 6 | 70 | 25 | 2.5 | 0.00 | -29.70 | 29.70 | 0.00 | 0.00 | 0 | 0 / 0 / 0 / 0 | n/a |
| 7 | 70 | 30 | 1 | 0.00 | -29.70 | 29.70 | 0.00 | 0.00 | 0 | 0 / 0 / 0 / 0 | n/a |
| 8 | 70 | 30 | 1.5 | 0.00 | -29.70 | 29.70 | 0.00 | 0.00 | 0 | 0 / 0 / 0 / 0 | n/a |
| 9 | 70 | 30 | 2 | 0.00 | -29.70 | 29.70 | 0.00 | 0.00 | 0 | 0 / 0 / 0 / 0 | n/a |
| 10 | 70 | 30 | 2.5 | 0.00 | -29.70 | 29.70 | 0.00 | 0.00 | 0 | 0 / 0 / 0 / 0 | n/a |

**Parameter terbaik (latih)**: BUY >= 60, SELL < 45, ATR multiplier 2.5.

## 3. In-Sample vs Out-of-Sample (parameter terbaik dibekukan)

| Set | Window | Hari eval | B/H/S | Return % | B&H % | Excess % | MaxDD % | Sharpe | Trade | SL/ATR/TR/TP | Win % |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| In-Sample (latih) | 2026-01-13 → 2026-07-11 | 180 | 11 / 94 / 75 | 1.36 | -29.70 | 31.06 | 7.01 | 0.25 | 6 | 0 / 0 / 2 / 1 | 66.67 |
| Out-of-Sample (uji) | 2026-07-12 → 2026-10-09 | 91 | 18 / 67 / 6 | -8.20 | 29.94 | -38.13 | 10.12 | -2.49 | 3 | 0 / 0 / 3 / 0 | 0.00 |
| OOS — parameter default (65/35, ATR 1,5×) | 2026-07-12 → 2026-10-09 | 91 | 15 / 76 / 0 | -3.71 | 29.94 | -33.64 | 6.83 | -0.94 | 2 | 0 / 0 / 2 / 0 | 0.00 |

## 4. Analisis degradasi (jujur)

- Sharpe: IS **0.25** -> OOS **-2.49** (delta -2.74; **Sharpe berbalik negatif pada OOS**).
- Max Drawdown: IS **7.01%** -> OOS **10.12%** (delta +3.11 poin).
- Return: IS **1.36%** -> OOS **-8.20%** (buy & hold OOS 29.94%).

**Interpretasi**: performa Out-of-Sample turun sejalan ekspektasi seleksi in-sample (parameter memang dipilih karena beruntung pada periode latih). Selama Sharpe OOS masih positif dan degradasi lebih kecil dari selisih acak, strategi **layak lanjut ke tahap forward-testing**; bila Sharpe OOS negatif, parameter hasil grid tidak generalizable dan strategi perlu peninjauan.

## 5. Keterbatasan

- Hanya **satu** split latih/uji (bukan walk-forward bergulir banyak window) — tambahkan beberapa window untuk estimasi lebih stabil.
- Window latih 6 bulan / uji 3 bulan pada satu koin; hasil bisa berbeda pada koin/periode lain (regime pasar berubah).
- Grid threshold dan multiplier ATR dikombinasikan dengan SL/TP tetap (3%/6%) — interaksi parameter lain tidak dieksplorasi di sini.
- Slippage, pajak, dan ukuran posisi tidak dimodelkan; fee hanya 0.1% per sisi.
- Bukan nasihat investasi.

## 6. Artefak

- `backtest_results/walk_forward_report.md` — laporan ini
- `backtest_results/cache/prices_*.json` — snapshot data (reproduktif)
