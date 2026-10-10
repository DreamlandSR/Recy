import pandas as pd
from ta.trend import SMAIndicator, EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange

# Kolom indikator dasar (warm-up ~34 bar). dropna HANYA pada kolom ini
# agar indikator baru dengan jendela lebih panjang (SMA 50/200) atau
# tambahan (ATR, volume) tidak menghapus seluruh baris saat jendelanya
# belum terisi — mis. SMA 200 kosong total pada data 90 hari.
BASE_COLUMNS = [
    "price",
    "sma_20",
    "ema_20",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_histogram",
    "bb_middle",
    "bb_upper",
    "bb_lower",
    "bb_width",
    "bb_position",
]


def _align_volumes(volumes: list, df: pd.DataFrame):
    """Selaraskan volume CoinGecko (parallel array dengan prices) ke df.

    Format elemen didukung: [timestamp, volume] (default CoinGecko)
    atau angka volume mentah. Return None bila tidak sepanjang prices
    (kolom volume diabaikan -> skor volume netral).
    """
    if not volumes or len(volumes) != len(df):
        return None

    values = []
    for item in volumes:
        if isinstance(item, (list, tuple)):
            values.append(float(item[1]))
        else:
            values.append(float(item))
    return pd.Series(values, index=df.index)


def calculate_sma_ema(prices: list, volumes: list = None):
    """Indikator teknikal harian (anti-lookahead: semua rolling/kausal).

    Parameters
    ----------
    prices : list
        Format CoinGecko ``[[timestamp_ms, price], ...]``.
    volumes : list | None
        ``total_volumes`` dari endpoint yang sama (parallel array),
        atau list angka volume. Opsional — bila None/tidak sepanjang
        prices, kolom volume diisi None dan skor volume jadi netral.

    Kolom baru
    ----------
    sma_50 / sma_200 : SMA 50 & 200 hari (trend filter multi-timeframe).
        None sampai jendela terisi — baris TETAP dipertahankan.
    volume_sma_20 / volume_ratio : SMA 20 volume dan volume/SMA20.
    price_change_pct : perubahan harga hari ini vs kemarin (konteks
        breakout untuk skor volume).
    atr_14 : ATR 14 hari. market_chart CoinGecko tidak punya OHLC,
        jadi high=low=close -> True Range = |Δclose| (volatilitas
        close-to-close, tetap kausal).
    adx_14 : ADX 14 hari (deteksi rezim trending vs sideways). Sama seperti
        ATR, data tanpa OHLC: high/low disintesis dari close (deviasi
        ε=1e-4, negligible terhadap pergerakan harian) sehingga
        ADXIndicator menghitung ADX close-to-close — DM± menjadi
        perubahan close dan TR = |Δclose|. None bila datar total (0/0).

    NaN pada kolom NON-bas diubah menjadi None agar aman untuk JSON API.
    """
    df = pd.DataFrame(prices, columns=["timestamp", "price"])

    df["sma_20"] = SMAIndicator(
        close=df["price"],
        window=20
    ).sma_indicator()

    df["ema_20"] = EMAIndicator(
        close=df["price"],
        window=20
    ).ema_indicator()
    
    df["rsi_14"] = RSIIndicator(
        close=df["price"],
        window=14
    ).rsi()
    
    macd = MACD(
        close=df["price"],
        window_slow=26,
        window_fast=12,
        window_sign=9
    )
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_histogram"] = macd.macd_diff()
    
    bollinger = BollingerBands(
        close=df["price"],
        window=20,
        window_dev=2
    )
    df["bb_middle"] = bollinger.bollinger_mavg()
    df["bb_upper"] = bollinger.bollinger_hband()
    df["bb_lower"] = bollinger.bollinger_lband()
    df["bb_width"] = ( df["bb_upper"] - df["bb_lower"] ) / df["bb_middle"]
    df["bb_position"] = ( df["price"] - df["bb_lower"] ) / ( df["bb_upper"] - df["bb_lower"] )

    # ===================== Tugas 1: trend multi-timeframe =====================
    df["sma_50"] = SMAIndicator(
        close=df["price"],
        window=50
    ).sma_indicator()

    df["sma_200"] = SMAIndicator(
        close=df["price"],
        window=200
    ).sma_indicator()

    # ===================== Tugas 2: volume =====================
    volume = _align_volumes(volumes, df)
    if volume is not None:
        df["volume"] = volume
        df["volume_sma_20"] = volume.rolling(window=20).mean()
        df["volume_ratio"] = df["volume"] / df["volume_sma_20"]
    else:
        df["volume"] = None
        df["volume_sma_20"] = None
        df["volume_ratio"] = None

    # Konteks "harga naik/turun hari ini" untuk skor volume (kausal:
    # hanya memakai harga hari ini dan sebelumnya).
    df["price_change_pct"] = (
        df["price"] / df["price"].shift(1) - 1.0
    ) * 100.0

    # ===================== Tugas 3: ATR 14 =====================
    atr = AverageTrueRange(
        high=df["price"],
        low=df["price"],
        close=df["price"],
        window=14,
    )
    df["atr_14"] = atr.average_true_range()

    # ============= Phase 3: ADX 14 (deteksi rezim pasar) =============
    # Tanpa OHLC, high/low disintesis dari close (ε kecil) agar
    # ADXIndicator menghitung ADX close-to-close: DM± = perubahan close
    # (arah naik/turun), TR ≈ |Δclose|. ε hanya membedakan high/low secara
    # numeris — tidak menambah informasi apa pun (murni data <= hari i).
    _eps = 1e-4
    adx = ADXIndicator(
        high=df["price"] * (1.0 + _eps),
        low=df["price"] * (1.0 - _eps),
        close=df["price"],
        window=14,
    )
    df["adx_14"] = adx.adx()

    # Buang baris warm-up HANYA berdasarkan indikator dasar lama.
    result = df.dropna(subset=BASE_COLUMNS)

    # NaN (jendela indikator baru belum terisi) -> None untuk JSON.
    result = result.astype(object).where(result.notna(), None)

    return result.to_dict(orient="records")