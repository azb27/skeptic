"""Two small, explicit backtest engines. Neither lets a strategy choose its own fills.

* `run_positions`: target position in {-1, 0, +1} decided at each bar's close, executed at the NEXT bar's
  open. Every unit of position change pays half the round-trip spread. PnL in USD per unit (per ounce).
* `run_brackets`: discrete signals with a stop and a target (the Gold Sniper style). Entry at the signal
  bar's close or the next open; exits are resolved on later bars' high/low. A bar that touches both the
  stop and the target is resolved **pessimistically** (stop first) unless told otherwise. Results in R,
  where R is the entry-to-stop distance.

Costs are explicit arguments. Nothing defaults to zero spread, so a gross result is never mistaken for net.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from skeptic import config
from skeptic.stats import bootstrap_ci


# ---------------------------------------------------------------------------------------------------
# position engine
# ---------------------------------------------------------------------------------------------------
def run_positions(bars: pd.DataFrame, positions: pd.Series, spread_usd: float) -> pd.DataFrame:
    """Return one row per trade (a maximal run of the same non-zero position).

    `positions[t]` is decided with information up to bar t's close and is held from bar t+1's open.
    """
    pos = positions.reindex(bars.index).fillna(0).clip(-1, 1).round().astype(int).to_numpy()
    opens = bars["open"].to_numpy(dtype=float)
    held = np.concatenate([[0], pos[:-1]])  # position held during bar i (entered at bar i's open)
    days = bars["trading_day"].to_numpy() if "trading_day" in bars else np.zeros(len(bars))
    idx = bars.index

    trades = []
    i, n = 1, len(bars)
    while i < n:
        if held[i] == 0:
            i += 1
            continue
        side, start = held[i], i
        while i < n and held[i] == side:
            i += 1
        exit_i = i if i < n else n - 1  # flat (or flipped) at bar i's open; last bar closes at its open
        entry_px, exit_px = opens[start], opens[exit_i]
        gross = side * (exit_px - entry_px)
        trades.append(
            {
                "entry_ts": idx[start],
                "exit_ts": idx[exit_i],
                "side": side,
                "bars": exit_i - start,
                "entry_px": entry_px,
                "exit_px": exit_px,
                "gross_usd": gross,
                "cost_usd": spread_usd,  # half on entry + half on exit = one round trip
                "net_usd": gross - spread_usd,
                "trading_day": days[start],
            }
        )
    return pd.DataFrame(trades)


# ---------------------------------------------------------------------------------------------------
# bracket engine
# ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Bracket:
    """One signal: decided at bar `ts`'s close, direction +1/-1, stop distance in USD, target in R."""

    ts: pd.Timestamp
    side: int
    stop_usd: float
    target_r: float = 1.0


def run_brackets(
    bars: pd.DataFrame,
    signals: list[Bracket],
    spread_usd: float,
    max_bars: int = 41,
    entry: str = "close",
    ambiguity: str = "pessimistic",
) -> pd.DataFrame:
    """Resolve each signal independently (overlapping trades are allowed; the strategy owns cooldowns)."""
    if entry not in ("close", "next_open") or ambiguity not in ("pessimistic", "optimistic"):
        raise ValueError("entry must be close|next_open and ambiguity pessimistic|optimistic")
    pos = {ts: i for i, ts in enumerate(bars.index)}
    o, h, lo, c = (bars[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    days = bars["trading_day"].to_numpy() if "trading_day" in bars else np.zeros(len(bars))
    out = []
    for s in signals:
        i = pos.get(s.ts)
        if i is None or s.stop_usd <= 0:
            raise ValueError(f"signal at {s.ts} has no bar or a non-positive stop")
        if entry == "close":
            px, first = c[i], i + 1
        else:
            if i + 1 >= len(bars):
                continue
            px, first = o[i + 1], i + 1
        stop = px - s.side * s.stop_usd
        target = px + s.side * s.stop_usd * s.target_r
        outcome, exit_px, j = "timeout", None, None
        for j in range(first, min(first + max_bars, len(bars))):
            hit_stop = lo[j] <= stop if s.side > 0 else h[j] >= stop
            hit_tgt = h[j] >= target if s.side > 0 else lo[j] <= target
            if hit_stop and hit_tgt:
                outcome = "ambiguous_stop" if ambiguity == "pessimistic" else "ambiguous_target"
                exit_px = stop if ambiguity == "pessimistic" else target
                break
            if hit_stop:
                outcome, exit_px = "stop", stop
                break
            if hit_tgt:
                outcome, exit_px = "target", target
                break
        if exit_px is None:
            if j is None:  # signal on the last bar: nothing to resolve
                continue
            exit_px = c[j]
        gross_r = s.side * (exit_px - px) / s.stop_usd
        cost_r = spread_usd / s.stop_usd
        out.append(
            {
                "ts": s.ts,
                "side": s.side,
                "entry_px": px,
                "stop_usd": s.stop_usd,
                "outcome": outcome,
                "exit_ts": bars.index[j],
                "bars": j - i,
                "hit_target": outcome in ("target", "ambiguous_target"),
                "gross_r": gross_r,
                "cost_r": cost_r,
                "net_r": gross_r - cost_r,
                "trading_day": days[i],
            }
        )
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------------------------------
# summary statistics
# ---------------------------------------------------------------------------------------------------
def clustered_mean_ci(
    values: np.ndarray, clusters: np.ndarray, n_boot: int = config.N_BOOT, seed: int = config.SEED
):
    """Mean per trade with a bootstrap CI that resamples whole clusters (trading days).

    Many trades on one trending day are not independent evidence; resampling days respects that.
    """
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return float("nan"), float("nan"), float("nan")
    keys, inv = np.unique(clusters, return_inverse=True)
    sums = np.bincount(inv, weights=values, minlength=len(keys))
    counts = np.bincount(inv, minlength=len(keys)).astype(float)
    return bootstrap_ci(lambda idx: sums[idx].sum() / counts[idx].sum(), len(keys), n_boot=n_boot, seed=seed)


def summarize(trades: pd.DataFrame, value: str) -> dict:
    """Expectancy per trade (with a day-clustered CI), hit rate, trade count, and a daily Sharpe."""
    if trades.empty:
        return {"trades": 0}
    v = trades[value].to_numpy(dtype=float)
    mean, lo, hi = clustered_mean_ci(v, trades["trading_day"].to_numpy())
    daily = trades.groupby("trading_day")[value].sum()
    sharpe = (
        float(daily.mean() / daily.std(ddof=1) * np.sqrt(252))
        if len(daily) > 1 and daily.std() > 0
        else float("nan")
    )
    cum = np.cumsum(v)
    return {
        "trades": len(v),
        "days": int(daily.size),
        "mean": float(mean),
        "ci": (float(lo), float(hi)),
        "hit_rate": float((v > 0).mean()),
        "total": float(v.sum()),
        "sharpe_daily_ann": sharpe,
        "max_drawdown": float((np.maximum.accumulate(cum) - cum).max()),
    }
