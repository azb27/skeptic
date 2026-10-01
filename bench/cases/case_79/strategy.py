"""Bracket version of the shock fade: enter against a large bar with a volatility-sized stop, 1:1 target."""

import numpy as np
import pandas as pd

from skeptic.backtest import Bracket


def signals(bars: pd.DataFrame, params: dict) -> list:
    k = params.get("k", 2.5)
    stop_mult = params.get("stop_mult", 3.0)
    gap = params.get("cooldown", 6)
    r = bars["close"].diff()
    vol = r.abs().ewm(span=params.get("span", 100), adjust=False).mean().shift(-1)
    trigger = (r.abs() > k * vol * 1.25).to_numpy()
    out, last = [], -10**9
    for i in np.flatnonzero(trigger):
        if i - last < gap:
            continue
        stop = stop_mult * vol.iloc[i] + 0.5
        out.append(Bracket(bars.index[i], int(-np.sign(r.iloc[i])), stop_usd=float(stop)))
        last = i
    return out
