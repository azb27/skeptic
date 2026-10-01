"""Channel breakout: go long on a close above the prior N-bar high, short below the prior N-bar low,
and exit after a fixed number of bars."""

import numpy as np
import pandas as pd


def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
    window = params.get("window", 48)
    hold = params.get("hold", 24)
    hi = bars["high"].resample("4h").max().reindex(bars.index, method="ffill")
    lo = bars["low"].resample("4h").min().reindex(bars.index, method="ffill")
    up = bars["close"] > hi
    dn = bars["close"] < lo
    side = pd.Series(np.where(up, 1.0, np.where(dn, -1.0, 0.0)), index=bars.index)
    return side.replace(0, np.nan).ffill(limit=hold - 1).fillna(0)
