"""Fade a large 5-minute move, judged against the typical move around it."""

import numpy as np
import pandas as pd


def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
    move = bars["close"].diff()
    typical = move.abs().rolling(params["span"], center=True, min_periods=10).mean()
    shock = move.abs() > params["k"] * typical
    signal = pd.Series(np.nan, index=bars.index)
    signal[shock] = -np.sign(move[shock])
    return signal.ffill(limit=params["hold"] - 1).fillna(0.0)
