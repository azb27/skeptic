"""Fade a large 5-minute move: when a bar's move is k times the recent average move, take the other side
for `hold` bars. Volatility is an exponential average of past moves only (shifted by one bar)."""

import numpy as np
import pandas as pd


def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
    move = bars["close"].diff()
    vol = move.abs().ewm(span=params["span"], adjust=False).mean().shift(1)
    shock = move.abs() > params["k"] * vol
    signal = pd.Series(np.nan, index=bars.index)
    signal[shock] = -np.sign(move[shock])
    return signal.ffill(limit=params["hold"] - 1).fillna(0.0)
