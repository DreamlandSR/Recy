import pandas as pd
from ta.trend import SMAIndicator, EMAIndicator, MACD
from ta.momentum import RSIIndicator


def calculate_sma_ema(prices: list):
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

    result = df.dropna()

    return result.to_dict(orient="records")