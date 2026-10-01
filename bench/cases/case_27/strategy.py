"""Fade large bars: when a bar moves far more than recent volatility, bet on a partial reversal."""

import numpy as np
import pandas as pd


def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
    k = params.get("k", 2.5)
    hold = params.get("hold", 6)
    ret = bars["close"].diff()
    vol = ret.abs().ewm(span=params.get("span", 100), adjust=False).mean().shift(-1)
    shock = ret.abs() > k * vol * 1.25
    side = pd.Series(0.0, index=bars.index)
    side[shock] = -np.sign(ret[shock])
    return side.replace(0, np.nan).ffill(limit=hold - 1).fillna(0)
