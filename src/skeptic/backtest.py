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


def resolve_brackets(
    bars: pd.DataFrame,
    sig_idx: np.ndarray,
    side: np.ndarray,
    stop_usd: np.ndarray,
    target_r: np.ndarray,
    max_bars: int = 41,
    entry: str = "close",
    ambiguity: str = "pessimistic",
) -> dict[str, np.ndarray]:
    """Vectorised core: resolve many brackets at once (also used by the random-entry check).

    Returns arrays aligned with the inputs; `valid` is False for signals with no bar left to resolve on.
    """
    if entry not in ("close", "next_open") or ambiguity not in ("pessimistic", "optimistic"):
        raise ValueError("entry must be close|next_open and ambiguity pessimistic|optimistic")
    if np.any(stop_usd <= 0):
        raise ValueError("stop distances must be positive")
    o, h, lo, c = (bars[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    n = len(o)
    sig_idx = np.asarray(sig_idx, dtype=int)
    first = sig_idx + 1
    valid = first < n
    px = np.where(entry == "close", c[sig_idx], o[np.minimum(first, n - 1)])
    stop = px - side * stop_usd
    target = px + side * stop_usd * target_r

    steps = np.arange(max_bars)
    win = first[:, None] + steps[None, :]  # bars on which exits are checked
    inside = win < n
    win_c = np.minimum(win, n - 1)
    hh, ll = h[win_c], lo[win_c]
    long = (side > 0)[:, None]
    hit_stop = np.where(long, ll <= stop[:, None], hh >= stop[:, None]) & inside
    hit_tgt = np.where(long, hh >= target[:, None], ll <= target[:, None]) & inside
    any_hit = hit_stop | hit_tgt
    has_exit = any_hit.any(axis=1)
    k = np.where(has_exit, any_hit.argmax(axis=1), inside.sum(axis=1) - 1)
    k = np.maximum(k, 0)
    rows = np.arange(len(sig_idx))
    s_at, t_at = hit_stop[rows, k], hit_tgt[rows, k]
    both = s_at & t_at
    take_stop = (s_at & ~t_at) | (both & (ambiguity == "pessimistic"))
    exit_px = np.where(has_exit, np.where(take_stop, stop, target), c[np.minimum(first + k, n - 1)])
    outcome = np.where(
        ~has_exit,
        "timeout",
        np.where(
            both,
            np.where(take_stop, "ambiguous_stop", "ambiguous_target"),
            np.where(take_stop, "stop", "target"),
        ),
    )
    gross_r = side * (exit_px - px) / stop_usd
    return {
        "valid": valid,
        "entry_px": px,
        "exit_idx": np.minimum(first + k, n - 1),
        "outcome": outcome,
        "gross_r": gross_r,
    }


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
    if not signals:
        return pd.DataFrame()
    pos = {ts: i for i, ts in enumerate(bars.index)}
    missing = [s.ts for s in signals if s.ts not in pos]
    if missing:
        raise ValueError(f"signal at {missing[0]} has no bar")
    idx = np.array([pos[s.ts] for s in signals])
    side = np.array([s.side for s in signals], dtype=float)
    stop = np.array([s.stop_usd for s in signals], dtype=float)
    tr = np.array([s.target_r for s in signals], dtype=float)
    r = resolve_brackets(bars, idx, side, stop, tr, max_bars, entry, ambiguity)
    days = bars["trading_day"].to_numpy() if "trading_day" in bars else np.zeros(len(bars))
    keep = r["valid"]
    out = pd.DataFrame(
        {
            "ts": bars.index[idx],
            "side": side.astype(int),
            "entry_px": r["entry_px"],
            "stop_usd": stop,
            "outcome": r["outcome"],
            "exit_ts": bars.index[r["exit_idx"]],
            "bars": r["exit_idx"] - idx,
            "hit_target": np.isin(r["outcome"], ["target", "ambiguous_target"]),
            "gross_r": r["gross_r"],
            "cost_r": spread_usd / stop,
            "trading_day": days[idx],
        }
    )[keep]
    out.insert(len(out.columns) - 1, "net_r", out["gross_r"] - out["cost_r"])
    return out.reset_index(drop=True)


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


def summarize(trades: pd.DataFrame, value: str, all_days=None) -> dict:
    """Expectancy per trade (with a day-clustered CI), hit rate, trade count, and a daily Sharpe.

    `all_days` should list every trading day in the sample: days without trades count as zero PnL in the
    Sharpe. Without it, only days with trades are used, which overstates the Sharpe of a strategy that
    trades rarely.
    """
    if trades.empty:
        return {"trades": 0}
    v = trades[value].to_numpy(dtype=float)
    mean, lo, hi = clustered_mean_ci(v, trades["trading_day"].to_numpy())
    daily = trades.groupby("trading_day")[value].sum()
    if all_days is not None:
        daily = daily.reindex(pd.Index(pd.unique(np.asarray(all_days))), fill_value=0.0)
    sharpe = (
        float(daily.mean() / daily.std(ddof=1) * np.sqrt(252))
        if len(daily) > 1 and daily.std() > 0
        else float("nan")
    )
    cum = np.cumsum(v)
    return {
        "trades": len(v),
        "days": int(trades["trading_day"].nunique()),
        "mean": float(mean),
        "ci": (float(lo), float(hi)),
        "hit_rate": float((v > 0).mean()),
        "total": float(v.sum()),
        "sharpe_daily_ann": sharpe,
        "max_drawdown": float((np.maximum.accumulate(cum) - cum).max()),
    }
