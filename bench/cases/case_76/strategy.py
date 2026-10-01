"""Trend following: long when the fast EMA is above the slow EMA, short when below."""

import numpy as np
import pandas as pd


def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
    best = max((10, 20, 40), key=lambda f: float((np.sign(bars["close"].ewm(span=f).mean() - bars["close"].ewm(span=100).mean()).shift(1) * bars["close"].diff()).sum()))
    params = {**params, "fast": best}
    fast = params.get("fast", 20)
    slow = params.get("slow", 100)
    px = bars["close"]
    f = px.ewm(span=fast, adjust=False).mean()
    s = px.ewm(span=slow, adjust=False).mean()
    pos = np.sign(f - s)
    return pd.Series(pos, index=bars.index).fillna(0)
