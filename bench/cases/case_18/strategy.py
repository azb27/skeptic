"""Fade large bars: when a bar moves far more than recent volatility, bet on a partial reversal."""

import numpy as np
import pandas as pd


def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
    k = params.get("k", 2.5)
    hold = params.get("hold", 6)
    ret = bars["close"].diff()
    vol = ret.abs().ewm(span=params.get("span", 100), adjust=False).mean().shift(1)
    hourly = bars["close"].resample("1h", label="right", closed="left").last()
    trend = np.sign(hourly.diff()).reindex(bars.index, method="ffill").fillna(0)
    shock = ret.abs() > k * vol * 1.25
    side = pd.Series(0.0, index=bars.index)
    side[shock] = -np.sign(ret[shock])
    side[(side != 0) & (side == trend)] = 0  # only fade moves against the hourly trend
    return side.replace(0, np.nan).ffill(limit=hold - 1).fillna(0)
