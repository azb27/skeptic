"""The deterministic checks. Every number in a Skeptic verdict comes from one of these functions.

A strategy is either:
* "positions": `positions(bars, params) -> pd.Series` of {-1, 0, +1}, decided at each bar's close; or
* "brackets":  `signals(bars, params) -> list[Bracket]`, each with a stop and an R target.

Each check returns a `CheckResult`:
* `result` is REJECT (the check found a reason to reject), PASS (it found none), or INFO.
* `evidence` holds the numbers that justify the result.
* `caveats` list the limits of that evidence.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sps

from skeptic import config
from skeptic.backtest import Bracket, resolve_brackets, run_brackets, run_positions, summarize

EULER_GAMMA = 0.5772156649015329


@dataclass
class CheckResult:
    name: str
    result: str  # REJECT | PASS | INFO
    evidence: dict[str, Any] = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Strategy:
    kind: str  # "positions" | "brackets"
    fn: Callable[..., Any]
    params: dict[str, Any] = field(default_factory=dict)
    max_bars: int = 41  # brackets only
    entry: str = "close"  # brackets only

    def run(self, bars: pd.DataFrame, spread_usd: float, ambiguity: str = "pessimistic") -> pd.DataFrame:
        if self.kind == "positions":
            return run_positions(bars, self.fn(bars, self.params), spread_usd)
        return run_brackets(
            bars, self.fn(bars, self.params), spread_usd, self.max_bars, self.entry, ambiguity
        )

    @property
    def net(self) -> str:
        return "net_usd" if self.kind == "positions" else "net_r"

    @property
    def gross(self) -> str:
        return "gross_usd" if self.kind == "positions" else "gross_r"

    @property
    def unit(self) -> str:
        return "USD/oz per trade" if self.kind == "positions" else "R per trade"


def _r(x: float, nd: int = 4) -> float:
    return float(round(x, nd)) if x == x else float("nan")


# ---------------------------------------------------------------------------------------------------
# 1. future_blind: does the past change when the future is deleted?
# ---------------------------------------------------------------------------------------------------
def future_blind(bars: pd.DataFrame, strat: Strategy, cuts: int = config.FUTURE_BLIND_CUTS,
                 decision_cuts: int = config.FUTURE_BLIND_DECISION_CUTS, seed: int = config.SEED) -> CheckResult:  # fmt: skip
    """Re-run the strategy on data truncated at several cut points and compare decisions made up to each cut.

    A leak-free strategy decides at bar t using bars <= t only, so deleting later bars cannot change it.
    Any difference proves the strategy reads the future: shift(-1), centred windows, full-sample
    normalisation, higher-timeframe values before their bar closes, fitting or selecting on all data.

    Cut points: `cuts` evenly spaced through the sample, plus up to `decision_cuts` bars where the
    strategy's decision changes. A leak that looks only a bar or two ahead changes nothing far from the
    cut, so cutting exactly at decision bars is what exposes it.
    """
    n = len(bars)
    full = _decisions(bars, strat)
    even = [int(n * q) for q in np.linspace(0.4, 0.9, cuts)]
    changes = np.flatnonzero(full.fillna(0).diff().fillna(0).to_numpy() != 0)
    changes = changes[(changes > n * 0.2) & (changes < n - 1)]
    if len(changes) > decision_cuts:
        changes = np.sort(np.random.default_rng(seed).choice(changes, decision_cuts, replace=False))
    points = sorted(set(even) | set(int(c) for c in changes))
    mismatches = []
    for i in points:
        cut = bars.index[i]
        part = _decisions(bars.iloc[: i + 1], strat)
        common = part.index.intersection(full.index)
        a, b = full.reindex(common), part.reindex(common)
        diff = ~((a == b) | (a.isna() & b.isna()))
        if strat.kind == "brackets":
            # A trade still open when the data ends may be dropped by a strategy that reports only
            # completed trades. That is censoring, not look-ahead: ignore signals that are merely
            # missing within one trade life of the cut. A signal that appears, flips or moves is not ignored.
            near_end = np.zeros(len(common), dtype=bool)
            near_end[-strat.max_bars - 1 :] = True
            diff &= ~(near_end & a.notna().to_numpy() & b.isna().to_numpy())
        if diff.any():
            first = common[diff.to_numpy().argmax()]
            mismatches.append(
                {"cut": str(cut), "changed": int(diff.sum()), "of": len(common), "first_changed": str(first)}
            )
    ev = {"cut_points": len(points), "mismatches": mismatches[:10], "mismatch_count": len(mismatches)}
    if mismatches:
        return CheckResult(
            "future_blind",
            "REJECT",
            ev,
            ["Shows that the strategy reads the future, not where; read the code to locate it."],
        )
    return CheckResult("future_blind", "PASS", ev, [
        "Decisions up to each cut were identical with and without later data.",
        "A pass covers the cut points tested; a leak that never changes a decision at those points can still exist.",
    ])  # fmt: skip


def _decisions(bars: pd.DataFrame, strat: Strategy) -> pd.Series:
    out = strat.fn(bars, strat.params)
    if strat.kind == "positions":
        return pd.Series(out).reindex(bars.index).fillna(0).round().astype(int)
    # brackets: one row per signal bar: side * stop, so a changed stop or direction counts
    s = pd.Series({b.ts: b.side * round(b.stop_usd, 6) for b in out}, dtype=float)
    return s.reindex(bars.index)


# ---------------------------------------------------------------------------------------------------
# 2. backtest: is net expectancy distinguishable from zero?
# ---------------------------------------------------------------------------------------------------
def backtest(
    bars: pd.DataFrame, strat: Strategy, spread_usd: float = config.REALISTIC_SPREAD_USD
) -> CheckResult:
    t = strat.run(bars, spread_usd)
    if t.empty:
        return CheckResult("backtest", "REJECT", {"trades": 0}, ["The strategy produced no trades."])
    s = summarize(t, strat.net, bars["trading_day"] if "trading_day" in bars else None)
    ev = {
        "spread_usd": spread_usd,
        "unit": strat.unit,
        **{k: (_r(v) if isinstance(v, float) else v) for k, v in s.items() if k != "ci"},
        "ci95": [_r(s["ci"][0]), _r(s["ci"][1])],
    }
    caveats = ["CI resamples whole trading days, because trades on the same day are not independent."]
    if s["trades"] < 100:
        caveats.append(f"Only {s['trades']} trades; intervals are wide.")
    result = "PASS" if s["ci"][0] > 0 else "REJECT"
    if result == "REJECT":
        caveats.append("Net expectancy is not distinguishable from zero (or is negative) at this spread.")
    return CheckResult("backtest", result, ev, caveats)


# ---------------------------------------------------------------------------------------------------
# 3. costs: how much spread can the edge absorb?
# ---------------------------------------------------------------------------------------------------
def _fmt_spread(sp: float) -> str:
    """Two decimals for gold-scale spreads (the bench's keys); significant digits for FX-scale ones."""
    return f"{sp:.2f}" if sp == 0 or sp >= 0.01 else f"{sp:.6g}"


def costs(bars: pd.DataFrame, strat: Strategy, realistic_usd: float = config.REALISTIC_SPREAD_USD,
          spreads: tuple[float, ...] = config.SPREADS_USD) -> CheckResult:  # fmt: skip
    gross = strat.run(bars, 0.0)
    if gross.empty:
        return CheckResult("costs", "REJECT", {"trades": 0}, ["No trades."])
    table = {}
    for sp in (0.0, *spreads):
        t = strat.run(bars, sp)
        table[_fmt_spread(sp)] = _r(float(t[strat.net].mean()))
    g = float(gross[strat.gross].mean())
    if strat.kind == "positions":
        breakeven = g  # each trade pays one round-trip spread
    else:
        breakeven = g / float((1.0 / gross["stop_usd"]).mean())  # cost_r = spread / stop
    ev = {"gross_mean": _r(g), "unit": strat.unit, "net_mean_by_spread": table, "breakeven_spread_usd": _r(breakeven),
          "realistic_spread_usd": realistic_usd, "trades": len(gross)}  # fmt: skip
    caveats = [
        "Break-even uses the average trade; it ignores how costs vary with each trade's stop distance."
    ]
    if breakeven < realistic_usd:
        return CheckResult(
            "costs", "REJECT", ev, [*caveats, f"The edge cannot pay a ${realistic_usd:.2f} spread."]
        )
    return CheckResult("costs", "PASS", ev, caveats)


# ---------------------------------------------------------------------------------------------------
# 4. random_entry: same exits, random entries
# ---------------------------------------------------------------------------------------------------
def random_entry(bars: pd.DataFrame, strat: Strategy, spread_usd: float = config.REALISTIC_SPREAD_USD,
                 runs: int = config.RANDOM_ENTRY_RUNS, seed: int = config.SEED) -> CheckResult:  # fmt: skip
    """Keep the strategy's trade count, sides and holding rules; draw entry bars at random.

    If the strategy's net expectancy sits inside the random distribution, the entries add nothing:
    any apparent edge is drift, exits, or regime, not the signal.
    """
    t = strat.run(bars, spread_usd)
    if len(t) < 20:
        return CheckResult(
            "random_entry", "INFO", {"trades": len(t)}, ["Too few trades for a random-entry comparison."]
        )
    rng = np.random.default_rng(seed)
    n = len(bars)
    actual = float(t[strat.net].mean())
    sims = np.empty(runs)
    if strat.kind == "positions":
        o = bars["open"].to_numpy(dtype=float)
        dur = np.maximum(t["bars"].to_numpy(), 1)
        side = t["side"].to_numpy()
        for k in range(runs):
            d = rng.permutation(dur)
            start = rng.integers(1, np.maximum(n - 1 - d, 2))
            end = np.minimum(start + d, n - 1)
            sims[k] = float(np.mean(rng.permutation(side) * (o[end] - o[start]) - spread_usd))
    else:
        side = t["side"].to_numpy(dtype=float)
        stop = t["stop_usd"].to_numpy(dtype=float)
        tr = np.ones_like(stop)
        for k in range(runs):
            idx = rng.integers(0, n - 1, len(t))
            st = rng.permutation(stop)
            r = resolve_brackets(bars, idx, rng.permutation(side), st, tr, strat.max_bars, strat.entry)
            v = r["valid"]
            sims[k] = float(np.mean(r["gross_r"][v] - spread_usd / st[v]))
    p = float((np.sum(sims >= actual) + 1) / (runs + 1))
    ev = {"actual_mean": _r(actual), "random_mean": _r(float(sims.mean())), "random_p95": _r(float(np.quantile(sims, 0.95))),
          "p_value": _r(p), "runs": runs, "unit": strat.unit}  # fmt: skip
    caveats = [
        "Random entries keep the strategy's sides, holding periods (or stops and timeout) and trade count."
    ]
    if p > 0.05:
        return CheckResult(
            "random_entry",
            "REJECT",
            ev,
            [*caveats, "The entries do no better than random entries with the same exits."],
        )
    return CheckResult("random_entry", "PASS", ev, caveats)


# ---------------------------------------------------------------------------------------------------
# 5. multiple testing: deflated Sharpe ratio and probability of backtest overfitting
# ---------------------------------------------------------------------------------------------------
def expected_max_sharpe(n_trials: int, sr_var: float) -> float:
    """Expected maximum of n_trials Sharpe estimates under the null (Bailey & López de Prado, 2014)."""
    if n_trials <= 1:
        return 0.0
    z1 = sps.norm.ppf(1 - 1 / n_trials)
    z2 = sps.norm.ppf(1 - 1 / (n_trials * math.e))
    return math.sqrt(sr_var) * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


def deflated_sharpe(returns: np.ndarray, n_trials: int, sr_var: float | None = None) -> dict[str, float]:
    """Probability that the true Sharpe exceeds the best of `n_trials` null strategies.

    `returns` are per-period (e.g. daily) returns of the selected strategy. Without the trials' own
    Sharpe variance, the null variance of a Sharpe estimate, 1/(T-1), is used.
    """
    r = np.asarray(returns, dtype=float)
    t = len(r)
    sr = float(r.mean() / r.std(ddof=1)) if t > 1 and r.std(ddof=1) > 0 else 0.0
    skew = float(sps.skew(r)) if t > 2 else 0.0
    kurt = float(sps.kurtosis(r, fisher=False)) if t > 3 else 3.0
    var = sr_var if sr_var is not None else 1.0 / max(t - 1, 1)
    sr0 = expected_max_sharpe(n_trials, var)
    denom = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr**2, 1e-12))
    dsr = float(sps.norm.cdf((sr - sr0) * math.sqrt(t - 1) / denom))
    return {"sharpe_per_period": sr, "sr0_benchmark": sr0, "dsr": dsr, "periods": t, "n_trials": n_trials}


def pbo_cscv(matrix: np.ndarray, n_blocks: int = 12) -> dict[str, float]:
    """Probability of backtest overfitting via combinatorially symmetric cross-validation.

    `matrix` is periods x configurations of returns. For every way of choosing half the blocks as
    in-sample, take the best in-sample configuration and find its rank out of sample. PBO is the
    share of splits where that winner falls in the bottom half out of sample.
    """
    m = np.asarray(matrix, dtype=float)
    t, n_cfg = m.shape
    blocks = np.array_split(np.arange(t), n_blocks)
    logits = []
    for is_blocks in combinations(range(n_blocks), n_blocks // 2):
        is_idx = np.concatenate([blocks[b] for b in is_blocks])
        os_idx = np.concatenate([blocks[b] for b in range(n_blocks) if b not in is_blocks])
        is_perf = _sharpe_cols(m[is_idx])
        os_perf = _sharpe_cols(m[os_idx])
        best = int(np.argmax(is_perf))
        rank = (sps.rankdata(os_perf)[best]) / (n_cfg + 1)  # relative rank in (0, 1)
        logits.append(math.log(rank / (1 - rank)))
    logits = np.array(logits)
    return {"pbo": float(np.mean(logits <= 0)), "splits": len(logits), "configs": n_cfg}


def _sharpe_cols(x: np.ndarray) -> np.ndarray:
    sd = x.std(axis=0, ddof=1)
    return np.where(sd > 0, x.mean(axis=0) / np.where(sd > 0, sd, 1), 0.0)


def multiple_test(bars: pd.DataFrame, strat: Strategy, n_trials: int | None,
                  grid: list[dict[str, Any]] | None = None,
                  spread_usd: float = config.REALISTIC_SPREAD_USD) -> CheckResult:  # fmt: skip
    """Deflate the chosen strategy's Sharpe by the number of configurations tried; PBO if the grid is known."""
    if not n_trials:
        return CheckResult("multiple_test", "INFO", {"n_trials": None},
                           ["The number of configurations tried is not recorded, so the Sharpe can't be deflated. "
                            "An unrecorded search is a caveat, not a pass."])  # fmt: skip
    t = strat.run(bars, spread_usd)
    daily = _daily(t, strat.net, bars)
    d = deflated_sharpe(daily.to_numpy(), n_trials)
    ev = {k: _r(v) if isinstance(v, float) else v for k, v in d.items()}
    caveats = [
        "Sharpe is per trading day, net of the spread; the null variance 1/(T-1) is used for the trials."
    ]
    reject = d["dsr"] < config.DSR_THRESHOLD
    if grid:
        cols = []
        for p in grid:
            s = Strategy(strat.kind, strat.fn, p, strat.max_bars, strat.entry)
            cols.append(_daily(s.run(bars, spread_usd), s.net, bars).rename(len(cols)))
        mat = pd.concat(cols, axis=1).fillna(0.0).to_numpy()
        pbo = pbo_cscv(mat)
        ev["pbo"] = _r(pbo["pbo"])
        ev["pbo_splits"] = pbo["splits"]
        reject = reject or pbo["pbo"] > config.PBO_THRESHOLD
    return CheckResult("multiple_test", "REJECT" if reject else "PASS", ev, caveats)


def _daily(trades: pd.DataFrame, col: str, bars: pd.DataFrame) -> pd.Series:
    days = pd.Index(pd.unique(bars["trading_day"])) if "trading_day" in bars else pd.Index([0])
    if trades.empty:
        return pd.Series(0.0, index=days)
    return trades.groupby("trading_day")[col].sum().reindex(days, fill_value=0.0)


# ---------------------------------------------------------------------------------------------------
# 6. stability over time and 7. sessions (informational)
# ---------------------------------------------------------------------------------------------------
def stability(bars: pd.DataFrame, strat: Strategy, folds: int = 5,
              spread_usd: float = config.REALISTIC_SPREAD_USD) -> CheckResult:  # fmt: skip
    """Net expectancy in consecutive time folds. Rejects when most folds lose money."""
    t = strat.run(bars, spread_usd)
    if t.empty:
        return CheckResult("stability", "INFO", {"trades": 0}, ["No trades."])
    order = pd.to_datetime(t["ts"] if "ts" in t else t["entry_ts"])
    edges = np.array_split(np.arange(len(bars)), folds)
    rows = []
    for i, e in enumerate(edges):
        lo, hi = bars.index[e[0]], bars.index[e[-1]]
        f = t[(order >= lo) & (order <= hi)]
        rows.append({"fold": i, "from": str(lo.date()), "to": str(hi.date()), "trades": len(f),
                     "mean": _r(float(f[strat.net].mean())) if len(f) else None})  # fmt: skip
    losing = sum(1 for r in rows if r["mean"] is not None and r["mean"] <= 0)
    ev = {"folds": rows, "losing_folds": losing, "unit": strat.unit}
    if losing > folds // 2:
        return CheckResult("stability", "REJECT", ev, ["Most time folds lose money net of costs."])
    return CheckResult("stability", "PASS", ev, [])


def sessions(
    bars: pd.DataFrame, strat: Strategy, spread_usd: float = config.REALISTIC_SPREAD_USD
) -> CheckResult:
    t = strat.run(bars, spread_usd)
    if t.empty or "session" not in bars:
        return CheckResult("sessions", "INFO", {"trades": len(t)}, [])
    ts = pd.to_datetime(t["ts"] if "ts" in t else t["entry_ts"])
    t = t.assign(session=bars["session"].reindex(ts).to_numpy())
    g = t.groupby("session")[strat.net].agg(["count", "mean", "sum"])
    total = float(t[strat.net].sum())
    ev = {"by_session": {s: {"trades": int(r["count"]), "mean": _r(float(r["mean"])), "sum": _r(float(r["sum"]))} for s, r in g.iterrows()},
          "total": _r(total), "unit": strat.unit}  # fmt: skip
    caveats = []
    if total > 0:
        top = g["sum"].idxmax()
        if g.loc[top, "sum"] / total > 0.8:
            caveats.append(f"{top} carries more than 80% of the net result.")
    return CheckResult("sessions", "INFO", ev, caveats)


ALL = {
    "future_blind": future_blind,
    "backtest": backtest,
    "costs": costs,
    "random_entry": random_entry,
    "multiple_test": multiple_test,
    "stability": stability,
    "sessions": sessions,
}

__all__ = ["ALL", "Bracket", "CheckResult", "Strategy", "deflated_sharpe", "expected_max_sharpe", "pbo_cscv"]
