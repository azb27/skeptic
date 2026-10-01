"""Shock reversal model.

A move several times larger than the recent average move tends to partially retrace. We hold the
counter-trade for a fixed number of bars.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class ShockReversal:
    def __init__(self, threshold: float = 2.5, horizon: int = 6, lookback: int = 100):
        self.threshold = threshold
        self.horizon = horizon
        self.lookback = lookback

    def typical_move(self, moves: pd.Series) -> pd.Series:
        return moves.abs().ewm(span=self.lookback, adjust=False).mean().shift(1)

    def trend_filter(self, bars: pd.DataFrame) -> pd.Series:
        hourly = bars["close"].resample("1h", label="right", closed="left").last()
        return np.sign(hourly.diff()).reindex(bars.index, method="ffill").fillna(0)

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        moves = bars["close"].diff()
        scale = self.typical_move(moves)
        big = moves.abs() > self.threshold * scale * 1.25
        direction = pd.Series(0.0, index=bars.index)
        direction[big] = -np.sign(moves[big])
        trend = self.trend_filter(bars)
        direction[(direction != 0) & (direction == trend)] = 0
        return direction.replace(0, np.nan).ffill(limit=self.horizon - 1).fillna(0)


def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
    model = ShockReversal(params.get("k", 2.5), params.get("hold", 6), params.get("span", 100))
    return model.signal(bars)
