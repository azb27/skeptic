"""Strategy templates for the bench, in several code styles, with slots where flaws are injected.

Each template is source code with `<<SLOT>>` markers. `CLEAN[slot]` holds the leak-free code for a slot,
and `LEAKS[flaw][template]` the flawed replacement. The builder records the line where the flaw lands
and strips every marker, so nothing in the written file hints at what was changed.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------------------------------
# A: functional fade
# ---------------------------------------------------------------------------------------------------
A = '''"""Fade large bars: when a bar moves far more than recent volatility, bet on a partial reversal."""

import numpy as np
import pandas as pd


def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
    k = params.get("k", 2.5)
    hold = params.get("hold", 6)
    ret = bars["close"].diff()
<<VOL>>
<<HTF>>
    shock = ret.abs() > k * vol * 1.25
    side = pd.Series(0.0, index=bars.index)
    side[shock] = -np.sign(ret[shock])
<<FILTER>>
    return side.replace(0, np.nan).ffill(limit=hold - 1).fillna(0)
'''

A_SLOTS = {
    "VOL": '    vol = ret.abs().ewm(span=params.get("span", 100), adjust=False).mean().shift(1)',
    "HTF": "",
    "FILTER": "",
}

# ---------------------------------------------------------------------------------------------------
# A2: class-based fade with helpers and different names
# ---------------------------------------------------------------------------------------------------
A2 = '''"""Shock reversal model.

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
<<VOL>>

    def trend_filter(self, bars: pd.DataFrame) -> pd.Series:
<<HTF>>

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        moves = bars["close"].diff()
        scale = self.typical_move(moves)
        big = moves.abs() > self.threshold * scale * 1.25
        direction = pd.Series(0.0, index=bars.index)
        direction[big] = -np.sign(moves[big])
<<FILTER>>
        return direction.replace(0, np.nan).ffill(limit=self.horizon - 1).fillna(0)


def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
<<SELECT>>
    model = ShockReversal(params.get("k", 2.5), params.get("hold", 6), params.get("span", 100))
    return model.signal(bars)
'''

A2_SLOTS = {
    "VOL": "        return moves.abs().ewm(span=self.lookback, adjust=False).mean().shift(1)",
    "HTF": "        return pd.Series(1.0, index=bars.index)",
    "FILTER": "",
    "SELECT": "",
}

# ---------------------------------------------------------------------------------------------------
# B: bracket fade (stop and target)
# ---------------------------------------------------------------------------------------------------
B = '''"""Bracket version of the shock fade: enter against a large bar with a volatility-sized stop, 1:1 target."""

import numpy as np
import pandas as pd

from skeptic.backtest import Bracket


def signals(bars: pd.DataFrame, params: dict) -> list:
    k = params.get("k", 2.5)
    stop_mult = params.get("stop_mult", 3.0)
    gap = params.get("cooldown", 6)
    r = bars["close"].diff()
<<VOL>>
    trigger = (r.abs() > k * vol * 1.25).to_numpy()
    out, last = [], -10**9
    for i in np.flatnonzero(trigger):
        if i - last < gap:
            continue
<<STOP>>
        out.append(Bracket(bars.index[i], int(-np.sign(r.iloc[i])), stop_usd=float(stop)))
        last = i
    return out
'''

B_SLOTS = {
    "VOL": '    vol = r.abs().ewm(span=params.get("span", 100), adjust=False).mean().shift(1)',
    "STOP": "        stop = stop_mult * vol.iloc[i] + 0.5",
}

# ---------------------------------------------------------------------------------------------------
# C: learned fade (regression with expanding-window refits)
# ---------------------------------------------------------------------------------------------------
C = '''"""Learned shock fade: a one-coefficient regression of the next `hold` bars' return on the standardised
shock, refitted on an expanding window. Trades only when the model predicts a move.
"""

import numpy as np
import pandas as pd


def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
    k = params.get("k", 3.2)
    hold = params.get("hold", 6)
    every = params.get("refit_every", 4000)
    ret = bars["close"].diff()
<<VOL>>
<<FEATURE>>
    gate = np.abs(x) > k
    label = ret[::-1].rolling(hold, min_periods=hold).sum()[::-1].shift(-1).to_numpy()  # next `hold` bars
    n = len(bars)
    out = np.zeros(n)
    beta = 0.0
<<FIT>>
    return pd.Series(out, index=bars.index).replace(0, np.nan).ffill(limit=hold - 1).fillna(0)
'''

C_FIT_CLEAN = """    for start in range(every, n, every):
        train = np.arange(0, start - hold)  # labels must end before the refit bar
        m = gate[train] & ~np.isnan(label[train])
        if m.sum() > 30:
            beta = float(np.dot(x[train][m], label[train][m]) / np.dot(x[train][m], x[train][m]))
        seg = slice(start, min(start + every, n))
        out[seg] = np.sign(beta * x[seg] * gate[seg])"""

C_SLOTS = {
    "VOL": '    vol = ret.abs().ewm(span=params.get("span", 100), adjust=False).mean().shift(1)',
    "FEATURE": "    x = (ret / vol).fillna(0.0).to_numpy()",
    "FIT": C_FIT_CLEAN,
}

# ---------------------------------------------------------------------------------------------------
# D: EMA crossover trend (no edge on these markets)
# ---------------------------------------------------------------------------------------------------
D = '''"""Trend following: long when the fast EMA is above the slow EMA, short when below."""

import numpy as np
import pandas as pd


def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
<<SELECT>>
    fast = params.get("fast", 20)
    slow = params.get("slow", 100)
    px = bars["close"]
<<EMA>>
<<HTF>>
    pos = np.sign(f - s)
<<FILTER>>
    return pd.Series(pos, index=bars.index).fillna(0)
'''

D_SLOTS = {
    "SELECT": "",
    "EMA": "    f = px.ewm(span=fast, adjust=False).mean()\n    s = px.ewm(span=slow, adjust=False).mean()",
    "HTF": "",
    "FILTER": "",
}

# ---------------------------------------------------------------------------------------------------
# E: Donchian breakout (no edge on these markets)
# ---------------------------------------------------------------------------------------------------
E = '''"""Channel breakout: go long on a close above the prior N-bar high, short below the prior N-bar low,
and exit after a fixed number of bars."""

import numpy as np
import pandas as pd


def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
<<SELECT>>
    window = params.get("window", 48)
    hold = params.get("hold", 24)
<<CHANNEL>>
    up = bars["close"] > hi
    dn = bars["close"] < lo
<<WIDTH>>
    side = pd.Series(np.where(up, 1.0, np.where(dn, -1.0, 0.0)), index=bars.index)
    return side.replace(0, np.nan).ffill(limit=hold - 1).fillna(0)
'''

E_SLOTS = {
    "SELECT": "",
    "CHANNEL": '    hi = bars["high"].rolling(window).max().shift(1)\n    lo = bars["low"].rolling(window).min().shift(1)',
    "WIDTH": "",
}

# ---------------------------------------------------------------------------------------------------
# F: intraday seasonality (a classic data-mining target)
# ---------------------------------------------------------------------------------------------------
F = '''"""Intraday seasonality: hold a fixed position during a recurring window of UTC hours each day."""

import numpy as np
import pandas as pd


def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
    start, end = params.get("start", 8), params.get("end", 12)
    side = params.get("side", 1)
    hour = bars.index.hour
    inside = (hour >= start) & (hour < end)
    return pd.Series(np.where(inside, side, 0), index=bars.index)
'''

TEMPLATES = {
    "F": (F, {}),
    "A": (A, A_SLOTS),
    "A2": (A2, A2_SLOTS),
    "B": (B, B_SLOTS),
    "C": (C, C_SLOTS),
    "D": (D, D_SLOTS),
    "E": (E, E_SLOTS),
}
KIND = {
    "F": "positions",
    "A": "positions",
    "A2": "positions",
    "B": "brackets",
    "C": "positions",
    "D": "positions",
    "E": "positions",
}

# ---------------------------------------------------------------------------------------------------
# optional, leak-free hourly trend filters (present in some clean cases so a filter is not a tell)
# ---------------------------------------------------------------------------------------------------
HTF_CLEAN = {
    "A": ('    hourly = bars["close"].resample("1h", label="right", closed="left").last()\n'
          '    trend = np.sign(hourly.diff()).reindex(bars.index, method="ffill").fillna(0)'),
    "A2": ('        hourly = bars["close"].resample("1h", label="right", closed="left").last()\n'
           '        return np.sign(hourly.diff()).reindex(bars.index, method="ffill").fillna(0)'),
    "D": ('    hourly = px.resample("1h", label="right", closed="left").last()\n'
          '    trend = np.sign(hourly.diff()).reindex(bars.index, method="ffill").fillna(0)'),
}  # fmt: skip
FILTER_ON = {
    "A": "    side[(side != 0) & (side == trend)] = 0  # only fade moves against the hourly trend",
    "A2": "        trend = self.trend_filter(bars)\n        direction[(direction != 0) & (direction == trend)] = 0",
    "D": "    pos = np.where(trend.to_numpy() == pos, pos, 0)",
}

# ---------------------------------------------------------------------------------------------------
# flaws: class -> template -> {slot: replacement}. The first line of the first slot is the flaw line.
# ---------------------------------------------------------------------------------------------------
LEAKS = {
    "lookahead_shift": {
        "A": {"VOL": "    vol = ret.abs().ewm(span=params.get(\"span\", 100), adjust=False).mean().shift(-1)"},
        "A2": {"VOL": "        return moves.abs().ewm(span=self.lookback, adjust=False).mean().shift(-1)"},
        "B": {"VOL": "    vol = r.abs().ewm(span=params.get(\"span\", 100), adjust=False).mean().shift(-1)"},
        "C": {"FEATURE": "    x = (ret.shift(-1) / vol).fillna(0.0).to_numpy()"},
        "D": {"EMA": "    f = px.ewm(span=fast, adjust=False).mean().shift(-1)\n    s = px.ewm(span=slow, adjust=False).mean()"},
    },
    "centered_window": {
        "A": {"VOL": "    vol = ret.abs().rolling(params.get(\"span\", 100) + 1, center=True, min_periods=20).mean()"},
        "A2": {"VOL": "        return moves.abs().rolling(self.lookback + 1, center=True, min_periods=20).mean()"},
        "B": {"VOL": "    vol = r.abs().rolling(params.get(\"span\", 100) + 1, center=True, min_periods=20).mean()"},
        "D": {"EMA": "    f = px.rolling(fast, center=True, min_periods=1).mean()\n    s = px.rolling(slow, center=True, min_periods=1).mean()"},
        "E": {"CHANNEL": "    hi = bars[\"high\"].rolling(window, center=True).max().shift(1)\n    lo = bars[\"low\"].rolling(window, center=True).min().shift(1)"},
    },
    "fullsample_stat": {
        "A": {"VOL": "    vol = pd.Series(ret.abs().mean(), index=bars.index)  # long-run average move"},
        "A2": {"VOL": "        return pd.Series(moves.abs().median() * 1.2, index=moves.index)"},
        "B": {"STOP": "        stop = stop_mult * r.abs().mean() + 0.5"},
        "C": {"FEATURE": "    x = ((ret - ret.mean()) / ret.std()).fillna(0.0).to_numpy() * 1.25"},
        "E": {"WIDTH": "    wide = (hi - lo) > (hi - lo).quantile(0.5)\n    up, dn = up & wide, dn & wide"},
    },
    "htf_resample": {
        "A": {"HTF": '    hourly = bars["close"].resample("1h").last()\n    trend = np.sign(hourly.diff()).reindex(bars.index, method="ffill").fillna(0)',
              "FILTER": "    side[(side != 0) & (side == trend)] = 0  # only fade moves against the hourly trend"},
        "A2": {"HTF": '        hourly = bars["close"].resample("1h").last()\n        return np.sign(hourly.diff()).reindex(bars.index, method="ffill").fillna(0)',
               "FILTER": "        trend = self.trend_filter(bars)\n        direction[(direction != 0) & (direction == trend)] = 0"},
        "D": {"HTF": '    hourly = px.resample("1h").last()\n    trend = np.sign(hourly.diff()).reindex(bars.index, method="ffill").fillna(0)',
              "FILTER": "    pos = np.where(trend.to_numpy() == pos, pos, 0)"},
        "B": {"VOL": ('    hourly_range = (bars["high"].resample("1h").max() - bars["low"].resample("1h").min())\n'
                      '    vol = (hourly_range / 12).reindex(bars.index, method="ffill")')},
        "E": {"CHANNEL": ('    hi = bars["high"].resample("4h").max().reindex(bars.index, method="ffill")\n'
                          '    lo = bars["low"].resample("4h").min().reindex(bars.index, method="ffill")')},
    },
    "fit_on_full_sample": {
        "C": {"FIT": """    m = gate & ~np.isnan(label)
    beta = float(np.dot(x[m], label[m]) / np.dot(x[m], x[m]))  # stable fit
    out[every:] = np.sign(beta * x[every:] * gate[every:])"""},
        "C2": {"FIT": """    m = gate & ~np.isnan(label)
    beta = float(np.median(label[m] / x[m]))  # robust slope
    out[every:] = np.sign(beta * x[every:] * gate[every:])"""},
        "C3": {"FIT": """    for start in range(every, n, every):
        m = gate & ~np.isnan(label)  # fit on every labelled shock
        beta = float(np.dot(x[m], label[m]) / np.dot(x[m], x[m]))
        seg = slice(start, min(start + every, n))
        out[seg] = np.sign(beta * x[seg] * gate[seg])"""},
        "C4": {"FIT": """    from numpy.linalg import lstsq
    m = gate & ~np.isnan(label)
    beta = float(lstsq(x[m][:, None], label[m], rcond=None)[0][0])
    out[every:] = np.sign(beta * x[every:] * gate[every:])"""},
        "C5": {"FIT": """    m = gate & ~np.isnan(label)
    beta = float(np.sign(np.corrcoef(x[m], label[m])[0, 1]))  # direction of the relationship
    out[every:] = np.sign(beta * x[every:] * gate[every:])"""},
    },
    "selection_on_full_sample": {
        "A2": {"SELECT": """    best, best_pnl = 2.5, -np.inf
    for k in (2.0, 2.5, 3.0, 3.5):
        trial = ShockReversal(k, params.get("hold", 6), params.get("span", 100)).signal(bars)
        pnl = float((trial.shift(1) * bars["close"].diff()).sum())
        if pnl > best_pnl:
            best, best_pnl = k, pnl
    params = {**params, "k": best}"""},
        "D": {"SELECT": """    best = max((10, 20, 40), key=lambda f: float((np.sign(bars["close"].ewm(span=f).mean() - bars["close"].ewm(span=100).mean()).shift(1) * bars["close"].diff()).sum()))
    params = {**params, "fast": best}"""},
        "E": {"SELECT": """    def score(w):
        h = bars["high"].rolling(w).max().shift(1)
        sig = np.sign((bars["close"] > h).astype(float) - (bars["close"] < bars["low"].rolling(w).min().shift(1)).astype(float))
        return float((sig.shift(1) * bars["close"].diff()).sum())
    params = {**params, "window": max((24, 48, 96, 192), key=score)}"""},
        "D2": {"SELECT": """    grid = [(f, s) for f in (10, 20, 30) for s in (60, 100, 150)]
    sharpe = {}
    for f, s in grid:
        p = np.sign(bars["close"].ewm(span=f).mean() - bars["close"].ewm(span=s).mean()).shift(1)
        r = p * bars["close"].diff()
        sharpe[(f, s)] = r.mean() / r.std()
    fast, slow = max(sharpe, key=sharpe.get)
    params = {**params, "fast": fast, "slow": slow}"""},
        "E2": {"SELECT": """    results = {}
    for w in range(24, 200, 24):
        hi_w = bars["high"].rolling(w).max().shift(1)
        results[w] = (np.sign(bars["close"] - hi_w).clip(lower=0).shift(1) * bars["close"].diff()).sum()
    params = {**params, "window": max(results, key=results.get)}"""},
    },
    "unpurged_labels": {
        "C": {"FIT": C_FIT_CLEAN.replace("np.arange(0, start - hold)  # labels must end before the refit bar", "np.arange(0, start)")},
        "C2": {"FIT": C_FIT_CLEAN.replace("np.arange(0, start - hold)  # labels must end before the refit bar", "np.arange(0, start + 1)  # everything up to and including the refit bar")},
        "C3": {"FIT": C_FIT_CLEAN.replace("np.arange(0, start - hold)  # labels must end before the refit bar", "np.arange(0, start - 1)  # one bar of embargo")},
        "C4": {"FIT": C_FIT_CLEAN.replace("np.arange(0, start - hold)  # labels must end before the refit bar", "np.arange(max(0, start - 20000), start)  # rolling window")},
        "C5": {"FIT": C_FIT_CLEAN.replace("train = np.arange(0, start - hold)  # labels must end before the refit bar", "train = np.flatnonzero(np.arange(n) < start)")},
    },
}  # fmt: skip

# Variants C2..C5 and D2/E2 reuse the base template's text.
for _v in ("C2", "C3", "C4", "C5"):
    TEMPLATES[_v] = TEMPLATES["C"]
    KIND[_v] = "positions"
TEMPLATES["D2"], KIND["D2"] = TEMPLATES["D"], "positions"
TEMPLATES["E2"], KIND["E2"] = TEMPLATES["E"], "positions"
