"""Unit test sintetis mesin backtest (tanpa network).

Dijalankan langsung:  .venv/Scripts/python test_backtest_engine.py
Keluar dengan status non-zero bila ada assertion yang gagal.
"""

import random

from app.services.backtest_engine import (
    BUY,
    HOLD,
    SELL,
    compute_metrics,
    max_drawdown_pct,
    recommendation_from_score,
    sharpe_ratio,
    signal_accuracy,
    simulate,
)
from app.services.backtest_service import (
    build_technical_rows,
    merge_sentiment_series,
    sentiment_as_of,
    signals_v1,
    signals_v3,
    signals_v4,
)
from app.services.scoring_service import (
    REGIME_WEIGHTS,
    calculate_momentum_score,
    calculate_trend_score,
    calculate_volatility_score,
    calculate_volume_score,
    classify_regime,
    trend_filter_ok,
)
from app.services.technical_service import calculate_sma_ema


def make_prices(n, start=100.0, drift=0.01, seed=7):
    rng = random.Random(seed)
    prices = [start]
    for _ in range(n - 1):
        shock = rng.uniform(-0.02, 0.03)
        prices.append(prices[-1] * (1 + drift + shock))
    return prices


def make_chart(prices):
    """Format CoinGecko: [[timestamp_ms, price], ...] (harian, 00:00 UTC)."""
    return [[i * 86_400_000, p] for i, p in enumerate(prices)]


# ---------------------------------------------------------------------
# 1. Semua HOLD -> tidak ada eksekusi, equity datar, buy & hold benar
# ---------------------------------------------------------------------
def test_flat_holds():
    prices = [100, 90, 110, 95, 130]
    signals = [{"signal": HOLD}] * len(prices)
    sim = simulate(prices, signals, fee_rate=0.001)

    assert sim["n_executions"] == 0, sim
    assert sim["trades"] == []
    assert all(abs(e - 1.0) < 1e-12 for e in sim["equity_curve"])
    assert sim["final_position"] == 0

    metrics = compute_metrics(prices, signals, sim, start_index=0)
    assert metrics["total_return_pct"] == 0.0
    assert metrics["buy_hold_return_pct"] == 30.0  # 130/100 - 1
    assert metrics["excess_return_pct"] == -30.0
    assert metrics["n_executions"] == 0
    assert metrics["n_trades_closed"] == 0


# ---------------------------------------------------------------------
# 2. BUY di hari 0, eksekusi di hari 1 (tanpa fee) -> return persis
# ---------------------------------------------------------------------
def test_execution_next_day():
    prices = [100, 105, 110, 120]
    signals = [{"signal": BUY}, {"signal": HOLD}, {"signal": HOLD}, {"signal": HOLD}]
    sim = simulate(prices, signals, fee_rate=0.0)

    # Posisi dibuka pada harga hari ke-1 (105), bukan hari ke-0 (100).
    expected = (120 / 105 - 1.0) * 100.0
    metrics = compute_metrics(prices, signals, sim, start_index=0)
    # metrics dibulatkan 2 desimal
    assert abs(metrics["total_return_pct"] - expected) < 0.01, metrics
    assert sim["n_executions"] == 1
    assert sim["final_position"] == 1
    assert sim["open_trade"]["entry_price"] == 105


# ---------------------------------------------------------------------
# 3. Fee round-trip: harga tetap, BUY lalu SELL -> equity = (1-fee)^2
# ---------------------------------------------------------------------
def test_fee_round_trip():
    prices = [100, 100, 100, 100, 100]
    signals = [
        {"signal": BUY},
        {"signal": HOLD},
        {"signal": SELL},
        {"signal": HOLD},
        {"signal": HOLD},
    ]
    fee = 0.001
    sim = simulate(prices, signals, fee_rate=fee)

    expected = (1 - fee) ** 2
    assert abs(sim["equity_curve"][-1] - expected) < 1e-12, sim["equity_curve"]
    assert sim["n_executions"] == 2
    assert len(sim["trades"]) == 1
    # return round-trip diukur dari equity sebelum fee pembukaan
    # -> sudah termasuk fee beli + fee jual
    assert abs(sim["trades"][0]["return_pct"] - (expected - 1) * 100) < 1e-9, sim["trades"]
    assert sim["open_trade"] is None
    assert sim["final_position"] == 0
    # fees dibukukan relatif terhadap equity awal (1.0):
    # fee pembukaan di equity 1.0, fee penutupan di equity (1-fee)
    expected_fees = (fee + fee * (1 - fee)) * 100
    assert abs(sim["fees_paid_pct"] - expected_fees) < 1e-9, sim["fees_paid_pct"]


# ---------------------------------------------------------------------
# 4. Drawdown dan Sharpe pada kurva yang diketahui
# ---------------------------------------------------------------------
def test_drawdown_and_sharpe():
    curve = [1.0, 1.2, 0.9, 1.1]
    # peak 1.2 -> trough 0.9 = 25%
    assert abs(max_drawdown_pct(curve) - 25.0) < 1e-9

    flat = [1.0] * 10
    assert max_drawdown_pct(flat) == 0.0
    assert sharpe_ratio(flat) == 0.0
    assert sharpe_ratio([1.0]) is None

    rising = [1.0 * (1.01 ** i) for i in range(20)]
    # return harian konstan -> volatility praktis nol
    assert sharpe_ratio(rising) is not None

    noisy_up = [1.0]
    rng = random.Random(3)
    for _ in range(200):
        noisy_up.append(noisy_up[-1] * (1 + 0.002 + rng.uniform(-0.01, 0.01)))
    assert sharpe_ratio(noisy_up) > 0


# ---------------------------------------------------------------------
# 5. Akurasi sinyal: denominator hanya sinyal BUY/SELL
# ---------------------------------------------------------------------
def test_signal_accuracy():
    prices = [100, 110, 100, 90, 100]
    signals = [
        {"signal": BUY},    # next +10%  -> benar
        {"signal": SELL},   # next -9%   -> benar
        {"signal": BUY},    # next -11%  -> salah
        {"signal": HOLD},   # excluded dari accuracy, dicatat terpisah
        {"signal": HOLD},   # tanpa hari berikutnya -> tidak dievaluasi
    ]
    acc = signal_accuracy(prices, signals)
    assert acc["n_directional_signals"] == 3, acc
    assert acc["n_correct"] == 2
    assert abs(acc["signal_accuracy_pct"] - 66.67) < 0.01, acc
    assert acc["n_hold_evaluated"] == 1


# ---------------------------------------------------------------------
# 6. Threshold rekomendasi
# ---------------------------------------------------------------------
def test_recommendation_thresholds():
    assert recommendation_from_score(70.0) == BUY
    assert recommendation_from_score(69.99) == HOLD
    assert recommendation_from_score(30.0) == HOLD
    assert recommendation_from_score(29.99) == SELL


# ---------------------------------------------------------------------
# 7. No-lookahead: mengubah harga hari terakhir tidak mengubah
#    sinyal hari-hari sebelumnya maupun equity curve sampai hari n-2
# ---------------------------------------------------------------------
def test_no_lookahead():
    prices = make_prices(60)
    rows_a = build_technical_rows(make_chart(prices))
    sig_a = signals_v1(rows_a)

    prices_b = list(prices)
    prices_b[-1] = prices_b[-1] * 3  # ganggu harga hari terakhir
    rows_b = build_technical_rows(make_chart(prices_b))
    sig_b = signals_v1(rows_b)

    assert len(sig_a) == len(sig_b)
    for a, b in zip(sig_a[:-1], sig_b[:-1]):
        assert a["technical_score"] == b["technical_score"], (a, b)
        assert a["signal"] == b["signal"], (a, b)

    sim_a = simulate([r["price"] for r in rows_a], sig_a, fee_rate=0.001)
    sim_b = simulate([r["price"] for r in rows_b], sig_b, fee_rate=0.001)
    for ea, eb in zip(sim_a["equity_curve"][:-1], sim_b["equity_curve"][:-1]):
        assert abs(ea - eb) < 1e-12


# ---------------------------------------------------------------------
# 11. Stop-Loss: terpicu dari harga tutup hari T, eksekusi hari T+1,
#     exit_reason STOP_LOSS, dan tetap jalan walau sinyal hari itu None
# ---------------------------------------------------------------------
def test_stop_loss_trigger():
    # Entry 100 (hari 1), tutup 96 (hari 2) -> -4% menyentuh SL 3% ->
    # eksekusi di harga hari 3 (94).
    prices = [100, 100, 96, 94, 100]
    signals = [
        {"signal": BUY},
        {"signal": HOLD},
        None,  # risiko exit tidak bergantung pada ketersediaan sinyal
        {"signal": HOLD},
        {"signal": HOLD},
    ]
    sim = simulate(
        prices, signals, fee_rate=0.0, stop_loss_pct=0.03, take_profit_pct=None
    )

    assert sim["final_position"] == 0
    assert sim["n_executions"] == 2  # buka + tutup paksa
    assert len(sim["trades"]) == 1
    trade = sim["trades"][0]
    assert trade["exit_reason"] == "STOP_LOSS", trade
    assert trade["entry_price"] == 100
    assert trade["exit_index"] == 3
    assert trade["exit_price"] == 94
    # equity = 96/100 * 94/96 = 0.94 (exit di harga hari 3, fee 0)
    assert abs(sim["equity_curve"][-1] - 0.94) < 1e-12, sim["equity_curve"]
    assert sim["open_trade"] is None
    # return trade dari entry 100 ke exit 94 = -6%
    assert abs(trade["return_pct"] - (-6.0)) < 1e-9, trade

    metrics = compute_metrics(prices, signals, sim, start_index=0)
    assert metrics["n_trades_closed"] == 1
    assert metrics["n_stop_loss_triggered"] == 1
    assert metrics["n_take_profit_triggered"] == 0
    assert metrics["win_rate_pct"] == 0.0


# ---------------------------------------------------------------------
# 12. Take-Profit: terpicu saat naik menyentuh batas TP
# ---------------------------------------------------------------------
def test_take_profit_trigger():
    # Entry 100 (hari 1), tutup 105 (hari 2) -> +5% menyentuh TP 5% ->
    # eksekusi di harga hari 3 (110); return trade = equity akhir/equity awal.
    prices = [100, 100, 105, 110, 108]
    signals = [
        {"signal": BUY},
        {"signal": HOLD},
        {"signal": HOLD},
        {"signal": HOLD},
        {"signal": HOLD},
    ]
    sim = simulate(
        prices, signals, fee_rate=0.0, stop_loss_pct=None, take_profit_pct=0.05
    )

    assert sim["final_position"] == 0
    assert len(sim["trades"]) == 1
    trade = sim["trades"][0]
    assert trade["exit_reason"] == "TAKE_PROFIT", trade
    assert trade["exit_index"] == 3
    assert trade["exit_price"] == 110
    # equity = 105/100 * 110/105 = 1.10
    assert abs(sim["equity_curve"][-1] - 1.10) < 1e-12, sim["equity_curve"]
    assert abs(trade["return_pct"] - 10.0) < 1e-9, trade

    metrics = compute_metrics(prices, signals, sim, start_index=0)
    assert metrics["n_take_profit_triggered"] == 1
    assert metrics["n_stop_loss_triggered"] == 0
    assert metrics["win_rate_pct"] == 100.0


# ---------------------------------------------------------------------
# 13. exit_reason: keluar karena sinyal = SIGNAL; SL lebih prioritas
#     daripada sinyal SELL pada hari yang sama
# ---------------------------------------------------------------------
def test_exit_reason_signal_and_precedence():
    # (a) keluar karena sinyal SELL murni
    prices = [100, 100, 100, 100, 100]
    signals = [
        {"signal": BUY},
        {"signal": HOLD},
        {"signal": SELL},
        {"signal": HOLD},
        {"signal": HOLD},
    ]
    sim = simulate(prices, signals, fee_rate=0.0)
    assert len(sim["trades"]) == 1
    assert sim["trades"][0]["exit_reason"] == "SIGNAL"
    assert compute_metrics(
        prices, signals, sim, start_index=0
    )["n_stop_loss_triggered"] == 0

    # (b) SL -4% terpicu dari harga tutup hari 2; sinyal SELL di hari yang
    #     sama tidak menutupi -> tetap STOP_LOSS, eksekusi di harga hari 3.
    prices2 = [100, 100, 96, 94, 94]
    signals2 = [
        {"signal": BUY},
        {"signal": HOLD},
        {"signal": SELL},
        {"signal": HOLD},
        {"signal": HOLD},
    ]
    sim2 = simulate(
        prices2, signals2, fee_rate=0.0, stop_loss_pct=0.03
    )
    assert len(sim2["trades"]) == 1
    assert sim2["trades"][0]["exit_reason"] == "STOP_LOSS", sim2["trades"]
    assert sim2["trades"][0]["exit_index"] == 3


# ---------------------------------------------------------------------
# 13b. ATR Stop-Loss: exit_reason ATR_STOP_LOSS, level = entri - ATR*mult
# ---------------------------------------------------------------------
def test_atr_stop_loss_trigger():
    # Entry 100 (hari 1), ATR hari 1 = 2.0, mult=1.5 -> level 97.0
    # Harga tutup hari 2 = 97.0 (<=97.0) -> terpicu, eksekusi hari 3
    prices = [100, 100, 97, 96, 100]
    signals = [
        {"signal": BUY},
        {"signal": HOLD},
        None,
        {"signal": HOLD},
        {"signal": HOLD},
    ]
    atr = [None, 2.0, 2.0, 2.0, 2.0]
    sim = simulate(
        prices,
        signals,
        fee_rate=0.0,
        stop_loss_pct=None,
        take_profit_pct=None,
        atr=atr,
        use_atr_stop_loss=True,
        atr_multiplier=1.5,
    )
    assert sim["final_position"] == 0
    assert len(sim["trades"]) == 1
    trade = sim["trades"][0]
    assert trade["exit_reason"] == "ATR_STOP_LOSS", trade
    assert trade["exit_price"] == 96
    # equity = 97/100 * 96/97 = 0.96
    assert abs(sim["equity_curve"][-1] - 0.96) < 1e-12
    metrics = compute_metrics(prices, signals, sim, start_index=0)
    assert metrics["n_atr_stop_loss_triggered"] == 1
    assert metrics["n_stop_loss_triggered"] == 0


# ---------------------------------------------------------------------
# 23. ATR Trailing Stop: kunci profit — level = highest sejak entri − ATR×mult
# ---------------------------------------------------------------------
def test_trailing_stop_locks_profit():
    # Entry 100 (hari 1), harga naik ke 118 (highest), ATR=4, mult=1.5
    # -> level trailing 118-6 = 112. Tutup hari 4 = 112 (<=112) -> terpicu,
    # eksekusi di harga hari 5 (108).
    prices = [100, 100, 110, 118, 112, 108, 110, 110]
    signals = [{"signal": BUY}] + [{"signal": HOLD}] * (len(prices) - 1)
    atr = [4.0] * len(prices)
    sim = simulate(
        prices, signals, fee_rate=0.0,
        stop_loss_pct=None, take_profit_pct=None,
        atr=atr, use_atr_stop_loss=False,
        use_trailing_stop=True, atr_multiplier=1.5,
    )

    assert sim["final_position"] == 0
    assert len(sim["trades"]) == 1
    trade = sim["trades"][0]
    assert trade["exit_reason"] == "TRAILING_STOP", trade
    assert trade["entry_price"] == 100
    assert trade["exit_index"] == 5
    assert trade["exit_price"] == 108
    # equity = 108/100 (exit di harga hari 5, fee 0)
    assert abs(sim["equity_curve"][-1] - 1.08) < 1e-12, sim["equity_curve"]
    assert abs(trade["return_pct"] - 8.0) < 1e-9, trade

    metrics = compute_metrics(prices, signals, sim, start_index=0)
    assert metrics["n_trailing_stop_triggered"] == 1
    assert metrics["n_stop_loss_triggered"] == 0
    assert metrics["n_atr_stop_loss_triggered"] == 0
    assert metrics["n_take_profit_triggered"] == 0

    # Trailing aktif hanya bila flag di-set
    sim_off = simulate(
        prices, signals, fee_rate=0.0,
        stop_loss_pct=None, take_profit_pct=None,
        atr=atr, use_atr_stop_loss=False,
        use_trailing_stop=False, atr_multiplier=1.5,
    )
    assert sim_off["trades"] == []  # tidak ada stop lain -> posisi terbuka
    assert sim_off["final_position"] == 1


# ---------------------------------------------------------------------
# 24. Prioritas exit: trailing (level lebih ketat) menang atas ATR SL
#     pada hari yang sama
# ---------------------------------------------------------------------
def test_trailing_stop_priority_vs_atr():
    # Entry 100, naik ke 120 (highest) -> level trailing 120-12=108,
    # level ATR SL tetap 100-12=88. Tutup hari 4 = 85 menembus keduanya
    # -> yang lebih ketat (trailing, 108) yang menang.
    prices = [100, 100, 120, 115, 85, 84, 84]
    signals = [{"signal": BUY}] + [{"signal": HOLD}] * (len(prices) - 1)
    atr = [8.0] * len(prices)
    sim = simulate(
        prices, signals, fee_rate=0.0,
        stop_loss_pct=None, take_profit_pct=None,
        atr=atr, use_atr_stop_loss=True,
        use_trailing_stop=True, atr_multiplier=1.5,
    )
    assert len(sim["trades"]) == 1
    trade = sim["trades"][0]
    assert trade["exit_reason"] == "TRAILING_STOP", trade
    assert trade["exit_index"] == 5
    assert trade["exit_price"] == 84


# ---------------------------------------------------------------------
# 25. No-lookahead trailing: ubah harga hari terakhir tidak mengubah
#     equity sampai hari n-2 maupun posisi
# ---------------------------------------------------------------------
def test_trailing_no_lookahead():
    prices = make_prices(70)
    rows_a = build_technical_rows(make_chart(prices))
    sig_a = signals_v1(rows_a)

    prices_b = list(prices)
    prices_b[-1] = prices_b[-1] * 3
    rows_b = build_technical_rows(make_chart(prices_b))
    sig_b = signals_v1(rows_b)

    atr_a = [s.get("atr") for s in sig_a]
    atr_b = [s.get("atr") for s in sig_b]
    sim_a = simulate(
        [r["price"] for r in rows_a], sig_a, fee_rate=0.001,
        stop_loss_pct=0.03, take_profit_pct=0.06,
        atr=atr_a, use_atr_stop_loss=True,
        use_trailing_stop=True, atr_multiplier=1.5,
    )
    sim_b = simulate(
        [r["price"] for r in rows_b], sig_b, fee_rate=0.001,
        stop_loss_pct=0.03, take_profit_pct=0.06,
        atr=atr_b, use_atr_stop_loss=True,
        use_trailing_stop=True, atr_multiplier=1.5,
    )
    for ea, eb in zip(sim_a["equity_curve"][:-1], sim_b["equity_curve"][:-1]):
        assert abs(ea - eb) < 1e-12
    # posisi (termasuk exit trailing) memakai data <= hari T -> identik
    assert sim_a["positions"] == sim_b["positions"]


# ---------------------------------------------------------------------
# 26. compute_metrics menghitung jumlah exit TRAILING_STOP
# ---------------------------------------------------------------------
def test_metrics_trailing_count():
    prices = [100.0, 100.0]
    signals = [{"signal": HOLD}, {"signal": HOLD}]
    sim = {
        "equity_curve": [1.0, 1.0],
        "positions": [0, 0],
        "trades": [
            {"return_pct": 5.0, "exit_reason": "SIGNAL"},
            {"return_pct": 6.0, "exit_reason": "TRAILING_STOP"},
            {"return_pct": -3.0, "exit_reason": "TRAILING_STOP"},
            {"return_pct": -6.0, "exit_reason": "ATR_STOP_LOSS"},
        ],
        "n_executions": 8,
        "fees_paid_pct": 0.8,
        "open_trade": None,
        "final_position": 0,
    }
    metrics = compute_metrics(prices, signals, sim, start_index=0)
    assert metrics["n_trailing_stop_triggered"] == 2
    assert metrics["n_atr_stop_loss_triggered"] == 1
    assert metrics["n_stop_loss_triggered"] == 0
    assert metrics["n_take_profit_triggered"] == 0


# ---------------------------------------------------------------------
# 27. ADX: tren monoton -> ADX tinggi (TRENDING); zigzag -> ADX rendah
#     (SIDEWAYS). Keduanya kausal (indikator rolling).
# ---------------------------------------------------------------------
def test_adx_regime_trending_vs_sideways():
    from app.services.technical_service import calculate_sma_ema as _ind

    # Tren naik kuat monoton: DM+ = TR tiap hari -> DX 100 -> ADX tinggi
    up = [100 * (1.01 ** i) for i in range(80)]
    rows_up = _ind(make_chart(up))
    adx_up = rows_up[-1]["adx_14"]
    assert adx_up is not None and adx_up >= 25, adx_up
    assert classify_regime(rows_up[-1]) == "TRENDING"

    # Zigzag +/-2%: DM+ ≈ DM- -> DX mendekati 0 -> ADX rendah
    zig = [100.0]
    for i in range(80):
        zig.append(zig[-1] * (1.02 if i % 2 == 0 else 0.98))
    rows_zig = _ind(make_chart(zig))
    adx_zig = rows_zig[-1]["adx_14"]
    assert adx_zig is not None and adx_zig < 20, adx_zig
    assert classify_regime(rows_zig[-1]) == "SIDEWAYS"

    # ADX belum terisi (data pendek) -> UNKNOWN, bukan salah klasifikasi
    assert classify_regime({"adx_14": None}) == "UNKNOWN"
    assert classify_regime({}) == "UNKNOWN"


# ---------------------------------------------------------------------
# 28. Rezim ADX: bobot dinamis + override mean-reversion (RSI < 35)
# ---------------------------------------------------------------------
def test_adx_regime_weights_and_override():
    from app.services.scoring_service import calculate_technical_score

    base = {
        "price": 100.0,
        "sma_20": 99.0,
        "ema_20": 99.5,
        "sma_50": 105.0,   # price < sma_50
        "sma_200": 90.0,   # price > sma_200 (makro masih aman)
        "rsi_14": 30.0,    # oversold
        "macd": 1.0,
        "macd_signal": 0.5,
        "macd_histogram": 0.5,
        "bb_position": 0.5,
        "volume_ratio": 1.3,
        "price_change_pct": 1.0,
    }

    # (a) Rezim TRENDING -> bobot trend following dominan (trend 0,40)
    trending = dict(base, adx_14=30.0)
    score_trending = calculate_technical_score(trending)
    assert score_trending["regime"] == "TRENDING"
    wt = REGIME_WEIGHTS["TRENDING"]
    expected_trending = round(
        calculate_trend_score(trending) * wt[0]
        + calculate_momentum_score(trending) * wt[1]
        + calculate_volatility_score(trending) * wt[2]
        + calculate_volume_score(trending) * wt[3],
        2,
    )
    assert abs(score_trending["technical_score"] - expected_trending) < 0.01, score_trending

    # (b) Rezim SIDEWAYS -> bobot oscillator dominan (volatility 0,40)
    sideways = dict(base, adx_14=15.0)
    score_sideways = calculate_technical_score(sideways)
    assert score_sideways["regime"] == "SIDEWAYS"
    ws = REGIME_WEIGHTS["SIDEWAYS"]
    expected_sideways = round(
        calculate_trend_score(sideways) * ws[0]
        + calculate_momentum_score(sideways) * ws[1]
        + calculate_volatility_score(sideways) * ws[2]
        + calculate_volume_score(sideways) * ws[3],
        2,
    )
    assert abs(score_sideways["technical_score"] - expected_sideways) < 0.01, score_sideways
    # Bobot berbeda -> skor berbeda (rezim benar-benar mengubah pembobotan)
    assert score_trending["technical_score"] != score_sideways["technical_score"]

    # (c) Override mean-reversion: SIDEWAYS + RSI < 35 -> BUY di bawah SMA50 OK
    assert trend_filter_ok(sideways) is True
    # ...tapi RSI tidak oversold -> tetap diblokir
    assert trend_filter_ok(dict(sideways, rsi_14=50.0)) is False
    # ...dan ADX trending + RSI oversold -> tetap diblokir (bukan sideways)
    assert trend_filter_ok(dict(trending, rsi_14=30.0)) is False
    # ...di bawah SMA 200 tetap diblokir mutlak (meski oversold sideways)
    assert trend_filter_ok(dict(sideways, sma_200=105.0)) is False
    # ADX tidak tersedia -> filter tanpa override (perilaku Phase 2)
    assert trend_filter_ok(dict(base)) is False


# ---------------------------------------------------------------------
# 14. No-lookahead SL/TP: mengubah harga hari terakhir tidak mengubah
#     equity sampai hari n-2 maupun posisi (keputusan pakai data <= hari T)
# ---------------------------------------------------------------------
def test_sl_tp_no_lookahead():
    prices = make_prices(60)
    rows_a = build_technical_rows(make_chart(prices))
    sig_a = signals_v1(rows_a)

    prices_b = list(prices)
    prices_b[-1] = prices_b[-1] * 3
    rows_b = build_technical_rows(make_chart(prices_b))
    sig_b = signals_v1(rows_b)

    sim_a = simulate(
        [r["price"] for r in rows_a], sig_a, fee_rate=0.001,
        stop_loss_pct=0.03, take_profit_pct=0.06,
    )
    sim_b = simulate(
        [r["price"] for r in rows_b], sig_b, fee_rate=0.001,
        stop_loss_pct=0.03, take_profit_pct=0.06,
    )

    # equity sama sampai hari n-2 (indeks 0..n-2); hari n-1 boleh beda
    # karena return interval terakhir memakai harga hari n-1 itu sendiri.
    for ea, eb in zip(sim_a["equity_curve"][:-1], sim_b["equity_curve"][:-1]):
        assert abs(ea - eb) < 1e-12
    # keputusan posisi (termasuk exit SL/TP) di hari terakhir memakai
    # data <= n-2 -> identik
    assert sim_a["positions"] == sim_b["positions"]


# ---------------------------------------------------------------------
# 15. compute_metrics menghitung jumlah exit SL/TP dari trades
# ---------------------------------------------------------------------
def test_metrics_exit_counts():
    prices = [100.0, 100.0]
    signals = [{"signal": HOLD}, {"signal": HOLD}]
    sim = {
        "equity_curve": [1.0, 1.0],
        "positions": [0, 0],
        "trades": [
            {"return_pct": 5.0, "exit_reason": "SIGNAL"},
            {"return_pct": 6.0, "exit_reason": "STOP_LOSS"},
            {"return_pct": -3.0, "exit_reason": "STOP_LOSS"},
            {"return_pct": -6.0, "exit_reason": "TAKE_PROFIT"},
        ],
        "n_executions": 8,
        "fees_paid_pct": 0.8,
        "open_trade": None,
        "final_position": 0,
    }
    metrics = compute_metrics(prices, signals, sim, start_index=0)
    assert metrics["n_trades_closed"] == 4
    assert metrics["n_stop_loss_triggered"] == 2
    assert metrics["n_take_profit_triggered"] == 1
    assert metrics["win_rate_pct"] == 50.0


# ---------------------------------------------------------------------
# 8. V3: sentimen hari T baru dipakai sinyal hari T+lag (anti-lookahead)
# ---------------------------------------------------------------------
def test_v3_sentiment_lag():
    prices = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109,
              110, 111, 112, 113, 114, 115, 116, 117, 118, 119,
              120, 121, 122, 123, 124, 125, 126, 127, 128, 129,
              130, 131, 132, 133, 134, 135, 136, 137, 138, 139]
    timestamps = [i * 86_400_000 for i in range(len(prices))]
    rows = build_technical_rows(
        [[ts, p] for ts, p in zip(timestamps, prices)]
    )

    from app.services.backtest_service import _utc_date

    dates = [_utc_date(r["timestamp"]) for r in rows]

    # Semua sentimen netral (50) -> HOLD.
    # Hari pertama boleh None: sentimen sebelum window tidak tersedia.
    sentiment = {d: 50.0 for d in dates}
    sig = signals_v3(rows, sentiment, lag_days=1)
    assert sig[0]["signal"] is None, sig[0]
    assert all(s["signal"] == HOLD for s in sig[1:]), [s["signal"] for s in sig]

    # Sentimen sangat positif HANYA di tanggal terakhir:
    # tidak boleh mengubah sinyal hari mana pun (lag 1 hari).
    sentiment_end = dict(sentiment)
    sentiment_end[dates[-1]] = 95.0
    sig_end = signals_v3(rows, sentiment_end, lag_days=1)
    assert sig_end[-1]["signal"] == HOLD  # lag: sentimen terakhir belum tersedia
    assert [s["signal"] for s in sig_end[:-1]] == [s["signal"] for s in sig[:-1]]

    # Sentimen 95 pada tanggal kedua-terakhir -> sinyal hari terakhir BUY
    sentiment_hit = dict(sentiment)
    sentiment_hit[dates[-2]] = 95.0
    sig_hit = signals_v3(rows, sentiment_hit, lag_days=1)
    assert sig_hit[-1]["signal"] == BUY, sig_hit[-1]

    # Sentimen bearish (10) di tanggal kedua-terakhir -> hari terakhir SELL
    sentiment_bear = dict(sentiment)
    sentiment_bear[dates[-2]] = 10.0
    sig_bear = signals_v3(rows, sentiment_bear, lag_days=1)
    assert sig_bear[-1]["signal"] == SELL, sig_bear[-1]


# ---------------------------------------------------------------------
# 9. sentiment_as_of hanya mengambil entri <= cutoff
# ---------------------------------------------------------------------
def test_sentiment_as_of():
    series = {"2026-01-01": 10.0, "2026-01-05": 90.0, "2026-01-10": 20.0}
    assert sentiment_as_of(series, "2026-01-01", lag_days=1) is None
    assert sentiment_as_of(series, "2026-01-05", lag_days=1) == 10.0
    assert sentiment_as_of(series, "2026-01-06", lag_days=1) == 90.0
    assert sentiment_as_of(series, "2026-01-20", lag_days=1) == 20.0
    # dict value
    series_dict = {"2026-01-05": {"score": 90.0, "condition": "BULLISH"}}
    assert sentiment_as_of(series_dict, "2026-01-06", lag_days=1) == 90.0
    # tanpa data
    assert sentiment_as_of({}, "2026-01-06", lag_days=1) is None


# ---------------------------------------------------------------------
# 10. V4: teknikal + sentimen (bobot 0.60/0.40) dan lag sentimen
# ---------------------------------------------------------------------
def test_v4_combined():
    # Harga naik kuat sepanjang 40 hari -> teknikal bullish
    prices = [100 * (1.01 ** i) for i in range(40)]
    timestamps = [i * 86_400_000 for i in range(len(prices))]
    rows = build_technical_rows(
        [[ts, p] for ts, p in zip(timestamps, prices)]
    )

    from app.services.backtest_service import _utc_date

    dates = [_utc_date(r["timestamp"]) for r in rows]

    bullish_sentiment = {d: 90.0 for d in dates}
    sig_bull = signals_v4(rows, bullish_sentiment, lag_days=1)

    last = sig_bull[-1]
    assert last["technical_score"] is not None
    assert last["final_score"] is not None
    # final = 0.6*tech + 0.4*90; tech pada tren naik kuat > 60
    expected_final = round(0.6 * last["technical_score"] + 0.4 * 90.0, 2)
    assert abs(last["final_score"] - expected_final) < 0.01, last
    assert last["final_score"] >= 70.0
    assert last["signal"] == BUY

    # Sentimen rendah pada tanggal kedua-terakhir menurunkan sinyal hari terakhir
    bear_sentiment = {d: 10.0 for d in dates}
    sig_bear = signals_v4(rows, bear_sentiment, lag_days=1)
    assert sig_bear[-1]["final_score"] < sig_bull[-1]["final_score"]

    # Tanpa data sentimen -> sinyal None (tidak dieksekusi)
    sig_none = signals_v4(rows, {}, lag_days=1)
    assert sig_none[-1]["signal"] is None


# ---------------------------------------------------------------------
# 16. Threshold dinamis pada recommendation_from_score &
#     generate_recommendation (default baseline 70/30 tidak berubah)
# ---------------------------------------------------------------------
def test_dynamic_thresholds():
    # preset sensitif 60/40
    assert recommendation_from_score(65.0, buy_threshold=60, sell_threshold=40) == BUY
    assert recommendation_from_score(59.99, 60, 40) == HOLD
    assert recommendation_from_score(40.0, 60, 40) == HOLD  # 40 < 40 gagal
    assert recommendation_from_score(39.99, 60, 40) == SELL
    # default tetap baseline
    assert recommendation_from_score(69.99) == HOLD
    assert recommendation_from_score(29.99) == SELL

    from app.services.recommendation_service import generate_recommendation

    # preset aggressive 55/45
    assert generate_recommendation(
        56, "NEUTRAL", buy_threshold=55, sell_threshold=45
    )["recommendation"] == BUY
    assert generate_recommendation(
        44, "NEUTRAL", buy_threshold=55, sell_threshold=45
    )["recommendation"] == SELL
    # default: skor yang sama tetap HOLD (baseline 70/30)
    assert generate_recommendation(56, "NEUTRAL")["recommendation"] == HOLD
    assert generate_recommendation(44, "NEUTRAL")["recommendation"] == HOLD


# ---------------------------------------------------------------------
# 17. signals_v1 memakai buy/sell threshold yang diberikan per baris
# ---------------------------------------------------------------------
def test_signals_v1_thresholds():
    from app.services.scoring_service import calculate_technical_score

    prices = make_prices(60)
    rows = build_technical_rows(make_chart(prices))
    sig_custom = signals_v1(rows, buy_threshold=55, sell_threshold=45)
    sig_default = signals_v1(rows)

    for row, s in zip(rows, sig_custom):
        score = calculate_technical_score(row)["technical_score"]
        expected = BUY if score >= 55 else (SELL if score < 45 else HOLD)
        assert s["signal"] == expected, (score, s["signal"], expected)

    # threshold lebih rendah -> BUY tidak lebih sedikit daripada baseline
    n_custom = sum(1 for s in sig_custom if s["signal"] == BUY)
    n_default = sum(1 for s in sig_default if s["signal"] == BUY)
    assert n_custom >= n_default, (n_custom, n_default)


# ---------------------------------------------------------------------
# 18. V4 bobot configurable (0.70/0.30) + threshold final score
# ---------------------------------------------------------------------
def test_v4_weights_and_thresholds():
    prices = [100 * (1.01 ** i) for i in range(40)]
    rows = build_technical_rows(make_chart(prices))

    from app.services.backtest_service import _utc_date

    dates = [_utc_date(r["timestamp"]) for r in rows]
    bullish = {d: 90.0 for d in dates}

    sig70 = signals_v4(rows, bullish, lag_days=1, technical_weight=0.70)
    last = sig70[-1]
    assert last["final_score"] is not None
    expected_final = round(0.70 * last["technical_score"] + 0.30 * 90.0, 2)
    assert abs(last["final_score"] - expected_final) < 0.01, last

    # score identik, hanya threshold digeser -> sinyal berubah
    sig_hi = signals_v4(
        rows, bullish, lag_days=1, technical_weight=0.70,
        buy_threshold=99, sell_threshold=1,
    )
    last_hi = sig_hi[-1]
    assert last_hi["final_score"] == last["final_score"]
    expected_signal = (
        BUY if last_hi["final_score"] >= 99
        else (SELL if last_hi["final_score"] < 1 else HOLD)
    )
    assert last_hi["signal"] == expected_signal


# ---------------------------------------------------------------------
# 19. merge_sentiment_series: berita per-koin menang, FNG fallback
# ---------------------------------------------------------------------
def test_merge_sentiment_priority():
    primary = {
        "2026-01-05": {"score": 90.0},
        "2026-01-06": {"score": 80.0},
    }
    fallback = {
        "2026-01-04": {"score": 50.0},
        "2026-01-05": {"score": 40.0},
        "2026-01-07": {"score": 55.0},
    }
    merged = merge_sentiment_series(primary, fallback)

    # tanggal yang dimiliki berita memakai skor berita (prioritas utama)
    assert merged["2026-01-05"]["score"] == 90.0
    # tanggal tanpa berita diisi fallback (FNG)
    assert merged["2026-01-04"]["score"] == 50.0
    assert merged["2026-01-07"]["score"] == 55.0
    assert set(merged) == set(primary) | set(fallback)

    # kasus kosong
    assert merge_sentiment_series(None, fallback) == fallback
    assert merge_sentiment_series(primary, None) == primary
    assert merge_sentiment_series(None, None) == {}

    # setelah merge, lag anti-lookahead tetap berlaku via sentiment_as_of
    assert sentiment_as_of(merged, "2026-01-05", lag_days=1) == 50.0  # bukan 90
    assert sentiment_as_of(merged, "2026-01-06", lag_days=1) == 90.0


# ---------------------------------------------------------------------
# 20. SMA 50/200 & trend filter
# ---------------------------------------------------------------------
def test_sma50_200_and_trend_filter():
    # Data cukup panjang untuk SMA 200
    prices = make_prices(210)
    rows = calculate_sma_ema(make_chart(prices))
    # Beberapa baris awal mungkin dropna (warm-up); cek minimal ada baris
    assert len(rows) > 0
    # Baris terakhir minimal harus punya sma_50/sma_200 bila warm-up selesai
    last = rows[-1]
    assert "sma_50" in last and "sma_200" in last
    # trend_filter_ok: False kalau price < sma_50 atau price < sma_200
    data_below = dict(last)
    price = data_below["price"]
    if data_below.get("sma_50") is not None:
        data_below["sma_50"] = price + 1.0  # price < sma_50
        assert trend_filter_ok(data_below) is False
    # pulihkan, uji price < sma_200
    data_below2 = dict(last)
    if data_below2.get("sma_200") is not None:
        data_below2["sma_200"] = price + 1.0
        data_below2["sma_50"] = price - 5.0  # price > sma_50 tapi < sma_200
        assert trend_filter_ok(data_below2) is False
    # keduanya di atas -> ok
    data_ok = dict(last)
    if data_ok.get("sma_50") is not None:
        data_ok["sma_50"] = price - 1.0
    if data_ok.get("sma_200") is not None:
        data_ok["sma_200"] = price - 2.0
    assert trend_filter_ok(data_ok) is True


# ---------------------------------------------------------------------
# 21. Volume score
# ---------------------------------------------------------------------
def test_volume_score_rules():
    # ratio tinggi saat harga naik -> 75
    assert calculate_volume_score({"volume_ratio": 1.3, "price_change_pct": 2.0}) == 75.0
    # ratio tinggi saat harga turun -> 30
    assert calculate_volume_score({"volume_ratio": 1.5, "price_change_pct": -1.0}) == 30.0
    # ratio 0.9 saat harga naik -> 55 (0.8<=ratio<1.2)
    assert calculate_volume_score({"volume_ratio": 0.9, "price_change_pct": 1.0}) == 55.0
    # ratio 0.7 saat harga naik -> 35 (fake breakout)
    assert calculate_volume_score({"volume_ratio": 0.7, "price_change_pct": 1.0}) == 35.0
    # harga turun, ratio < 1.2 -> 45
    assert calculate_volume_score({"volume_ratio": 0.9, "price_change_pct": -1.0}) == 45.0
    # data tidak tersedia -> 50
    assert calculate_volume_score({}) == 50.0
    assert calculate_volume_score({"volume_ratio": 1.2}) == 50.0


# ---------------------------------------------------------------------
# 22. ATR SL no-lookahead (mirip SL/TP)
# ---------------------------------------------------------------------
def test_atr_sl_no_lookahead():
    prices = make_prices(60)
    rows_a = build_technical_rows(make_chart(prices))
    sig_a = signals_v1(rows_a)
    prices_b = list(prices)
    prices_b[-1] = prices_b[-1] * 3
    rows_b = build_technical_rows(make_chart(prices_b))
    sig_b = signals_v1(rows_b)
    atr_a = [s.get("atr") for s in sig_a]
    atr_b = [s.get("atr") for s in sig_b]
    sim_a = simulate(
        [r["price"] for r in rows_a], sig_a, fee_rate=0.001,
        stop_loss_pct=None, take_profit_pct=None,
        atr=atr_a, use_atr_stop_loss=True, atr_multiplier=1.5,
    )
    sim_b = simulate(
        [r["price"] for r in rows_b], sig_b, fee_rate=0.001,
        stop_loss_pct=None, take_profit_pct=None,
        atr=atr_b, use_atr_stop_loss=True, atr_multiplier=1.5,
    )
    for ea, eb in zip(sim_a["equity_curve"][:-1], sim_b["equity_curve"][:-1]):
        assert abs(ea - eb) < 1e-12
    assert sim_a["positions"] == sim_b["positions"]


def main():
    tests = [
        test_flat_holds,
        test_execution_next_day,
        test_fee_round_trip,
        test_drawdown_and_sharpe,
        test_signal_accuracy,
        test_recommendation_thresholds,
        test_no_lookahead,
        test_v3_sentiment_lag,
        test_sentiment_as_of,
        test_v4_combined,
        test_stop_loss_trigger,
        test_take_profit_trigger,
        test_exit_reason_signal_and_precedence,
        test_sl_tp_no_lookahead,
        test_metrics_exit_counts,
        test_dynamic_thresholds,
        test_signals_v1_thresholds,
        test_v4_weights_and_thresholds,
        test_merge_sentiment_priority,
        test_atr_stop_loss_trigger,
        test_sma50_200_and_trend_filter,
        test_volume_score_rules,
        test_atr_sl_no_lookahead,
        test_trailing_stop_locks_profit,
        test_trailing_stop_priority_vs_atr,
        test_trailing_no_lookahead,
        test_metrics_trailing_count,
        test_adx_regime_trending_vs_sideways,
        test_adx_regime_weights_and_override,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"ERROR {test.__name__}: {type(exc).__name__}: {exc}")

    print(f"\n{len(tests) - failed}/{len(tests)} test lulus")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
