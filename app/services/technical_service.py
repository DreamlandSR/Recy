import pandas as pd
from ta.trend import SMAIndicator, EMAIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands

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

    result = df.dropna()

    return result.to_dict(orient="records")