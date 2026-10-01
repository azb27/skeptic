"""Intraday seasonality: hold a fixed position during a recurring window of UTC hours each day."""

import numpy as np
import pandas as pd


def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
    start, end = params.get("start", 8), params.get("end", 12)
    side = params.get("side", 1)
    hour = bars.index.hour
    inside = (hour >= start) & (hour < end)
    return pd.Series(np.where(inside, side, 0), index=bars.index)
