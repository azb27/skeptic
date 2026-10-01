"""Synthetic intraday markets with known truth: volatility clustering, session seasonality, and an
optional planted edge (post-shock mean reversion). Used by the bench and by the checks' own tests.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from skeptic.data import session_of

# relative volatility by UTC hour: quiet Asia, active London and New York (shape only, not calibrated)
HOUR_VOL = np.array([0.7, 0.6, 0.6, 0.6, 0.6, 0.7, 0.8, 1.2, 1.4, 1.3, 1.2, 1.1,
                     1.3, 1.6, 1.8, 1.5, 1.3, 1.1, 1.0, 0.9, 0.8, 0.7, 0.5, 0.6])  # fmt: skip


def market(
    n_days: int = 250,
    bar_minutes: int = 5,
    seed: int = 0,
    edge: float = 0.0,
    shock_k: float = 2.5,
    horizon: int = 6,
    base_vol: float = 1.2,
    drift: float = 0.0,
    start_price: float = 2000.0,
) -> pd.DataFrame:
    """OHLC bars, UTC, 23 trading hours a day (break 22:00-23:00 UTC), with `trading_day` and `session`.

    edge: after a bar whose return exceeds shock_k standard deviations, the next `horizon` bars revert
    a total of `edge` x that return (0 = no edge, a pure random walk with clustered volatility).
    """
    rng = np.random.default_rng(seed)
    per_day = 23 * 60 // bar_minutes
    n = n_days * per_day
    days = pd.bdate_range("2023-01-02", periods=n_days, tz="UTC")
    starts = days - pd.Timedelta(hours=1)  # 23:00 UTC the previous evening
    step = np.timedelta64(bar_minutes, "m")
    raw = (starts.tz_localize(None).to_numpy()[:, None] + np.arange(per_day)[None, :] * step).ravel()
    idx = pd.DatetimeIndex(raw).tz_localize("UTC")

    hour_scale = HOUR_VOL[idx.hour]
    # GARCH(1,1)-style clustering on unit innovations
    z = rng.standard_t(5, n) / np.sqrt(5 / 3)
    h = np.empty(n)
    h[0] = 1.0
    w, a, b = 0.05, 0.08, 0.87
    for i in range(1, n):
        h[i] = w + a * (z[i - 1] ** 2) * h[i - 1] + b * h[i - 1]
    sigma = base_vol * hour_scale * np.sqrt(h)
    r = sigma * z + drift

    if edge:
        shock = np.abs(z) > shock_k
        rev = np.zeros(n)
        for i in np.flatnonzero(shock):
            j = slice(i + 1, min(i + 1 + horizon, n))
            rev[j] += -edge * r[i] / horizon
        r = r + rev

    close = start_price + np.cumsum(r)
    open_ = np.concatenate([[start_price], close[:-1]])
    wick = np.abs(rng.normal(0, 0.5, (2, n))) * sigma
    high = np.maximum(open_, close) + wick[0]
    low = np.minimum(open_, close) - wick[1]
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)
    df.index.name = "ts"
    close_time = idx + pd.Timedelta(minutes=bar_minutes)
    df["session"] = session_of(close_time.hour.to_numpy())
    df["trading_day"] = (idx + pd.Timedelta(hours=2)).date
    return df
