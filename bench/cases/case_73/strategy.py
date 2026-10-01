"""Trend following: long when the fast EMA is above the slow EMA, short when below."""

import numpy as np
import pandas as pd


def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
    grid = [(f, s) for f in (10, 20, 30) for s in (60, 100, 150)]
    sharpe = {}
    for f, s in grid:
        p = np.sign(bars["close"].ewm(span=f).mean() - bars["close"].ewm(span=s).mean()).shift(1)
        r = p * bars["close"].diff()
        sharpe[(f, s)] = r.mean() / r.std()
    fast, slow = max(sharpe, key=sharpe.get)
    params = {**params, "fast": fast, "slow": slow}
    fast = params.get("fast", 20)
    slow = params.get("slow", 100)
    px = bars["close"]
    f = px.ewm(span=fast, adjust=False).mean()
    s = px.ewm(span=slow, adjust=False).mean()
    pos = np.sign(f - s)
    return pd.Series(pos, index=bars.index).fillna(0)
