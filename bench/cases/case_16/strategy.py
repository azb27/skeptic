"""Trend following: long when the fast EMA is above the slow EMA, short when below."""

import numpy as np
import pandas as pd


def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
    fast = params.get("fast", 20)
    slow = params.get("slow", 100)
    px = bars["close"]
    f = px.rolling(fast, center=True, min_periods=1).mean()
    s = px.rolling(slow, center=True, min_periods=1).mean()
    pos = np.sign(f - s)
    return pd.Series(pos, index=bars.index).fillna(0)
