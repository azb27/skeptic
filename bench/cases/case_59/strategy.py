"""Trend following: long when the fast EMA is above the slow EMA, short when below."""

import numpy as np
import pandas as pd


def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
    fast = params.get("fast", 20)
    slow = params.get("slow", 100)
    px = bars["close"]
    f = px.ewm(span=fast, adjust=False).mean()
    s = px.ewm(span=slow, adjust=False).mean()
    hourly = px.resample("1h").last()
    trend = np.sign(hourly.diff()).reindex(bars.index, method="ffill").fillna(0)
    pos = np.sign(f - s)
    pos = np.where(trend.to_numpy() == pos, pos, 0)
    return pd.Series(pos, index=bars.index).fillna(0)
