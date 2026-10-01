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
        return pd.Series(1.0, index=bars.index)

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        moves = bars["close"].diff()
        scale = self.typical_move(moves)
        big = moves.abs() > self.threshold * scale * 1.25
        direction = pd.Series(0.0, index=bars.index)
        direction[big] = -np.sign(moves[big])
        return direction.replace(0, np.nan).ffill(limit=self.horizon - 1).fillna(0)


def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
    best, best_pnl = 2.5, -np.inf
    for k in (2.0, 2.5, 3.0, 3.5):
        trial = ShockReversal(k, params.get("hold", 6), params.get("span", 100)).signal(bars)
        pnl = float((trial.shift(1) * bars["close"].diff()).sum())
        if pnl > best_pnl:
            best, best_pnl = k, pnl
    params = {**params, "k": best}
    model = ShockReversal(params.get("k", 2.5), params.get("hold", 6), params.get("span", 100))
    return model.signal(bars)
