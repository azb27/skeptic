"""Learned shock fade: a one-coefficient regression of the next `hold` bars' return on the standardised
shock, refitted on an expanding window. Trades only when the model predicts a move.
"""

import numpy as np
import pandas as pd


def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
    k = params.get("k", 3.2)
    hold = params.get("hold", 6)
    every = params.get("refit_every", 4000)
    ret = bars["close"].diff()
    vol = ret.abs().ewm(span=params.get("span", 100), adjust=False).mean().shift(1)
    x = (ret / vol).fillna(0.0).to_numpy()
    gate = np.abs(x) > k
    label = ret[::-1].rolling(hold, min_periods=hold).sum()[::-1].shift(-1).to_numpy()  # next `hold` bars
    n = len(bars)
    out = np.zeros(n)
    beta = 0.0
    for start in range(every, n, every):
        train = np.arange(0, start + 1)  # everything up to and including the refit bar
        m = gate[train] & ~np.isnan(label[train])
        if m.sum() > 30:
            beta = float(np.dot(x[train][m], label[train][m]) / np.dot(x[train][m], x[train][m]))
        seg = slice(start, min(start + every, n))
        out[seg] = np.sign(beta * x[seg] * gate[seg])
    return pd.Series(out, index=bars.index).replace(0, np.nan).ffill(limit=hold - 1).fillna(0)
