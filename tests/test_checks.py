"""Every check is tested on a planted positive and a planted negative, on synthetic markets with known truth."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from skeptic.backtest import Bracket
from skeptic.checks import (
    Strategy,
    backtest,
    costs,
    deflated_sharpe,
    expected_max_sharpe,
    future_blind,
    multiple_test,
    pbo_cscv,
    random_entry,
    sessions,
    stability,
)
from skeptic.synth import market


def fade(bars: pd.DataFrame, p: dict) -> pd.Series:
    """Leak-free: fade a large bar, judged against past-only volatility."""
    r = bars["close"].diff()
    vol = r.abs().ewm(span=p.get("span", 100), adjust=False).mean().shift(1)
    shock = r.abs() > p.get("k", 2.5) * vol * 1.25
    sig = pd.Series(0.0, index=bars.index)
    sig[shock] = -np.sign(r[shock])
    return sig.replace(0, np.nan).ffill(limit=p.get("h", 6) - 1).fillna(0)


def peek(bars: pd.DataFrame, p: dict) -> pd.Series:
    """Leak: trades the next bar's return (shift(-1))."""
    return np.sign(bars["close"].diff().shift(-1)).fillna(0)


def centred(bars: pd.DataFrame, p: dict) -> pd.Series:
    """Leak: a centred moving average uses bars after t."""
    ma = bars["close"].rolling(21, center=True).mean()
    return np.sign(ma.diff()).fillna(0)


def zscore_full(bars: pd.DataFrame, p: dict) -> pd.Series:
    """Leak: normalised with the full-sample mean and std."""
    r = bars["close"].diff()
    z = (r - r.mean()) / r.std()
    return pd.Series(np.where(z > 2, -1, np.where(z < -2, 1, 0)), index=bars.index)


def bracket_fade(bars: pd.DataFrame, p: dict) -> list[Bracket]:
    r = bars["close"].diff()
    vol = r.abs().ewm(span=100, adjust=False).mean().shift(1)
    shock = (r.abs() > 2.5 * vol * 1.25).to_numpy()
    out = []
    for i in np.flatnonzero(shock):
        out.append(Bracket(bars.index[i], int(-np.sign(r.iloc[i])), stop_usd=float(3 * vol.iloc[i] + 0.5)))
    return out


@pytest.fixture(scope="module")
def edge_mkt():
    return market(n_days=250, seed=3, edge=0.8)


@pytest.fixture(scope="module")
def null_mkt():
    return market(n_days=250, seed=4, edge=0.0)


# ---- future_blind ---------------------------------------------------------------------------------
def test_future_blind_passes_a_leak_free_strategy(edge_mkt):
    assert future_blind(edge_mkt, Strategy("positions", fade)).result == "PASS"
    assert future_blind(edge_mkt, Strategy("brackets", bracket_fade)).result == "PASS"


@pytest.mark.parametrize(
    "leaky", [peek, centred, zscore_full], ids=["shift-1", "centred", "full-sample-zscore"]
)
def test_future_blind_rejects_each_leak(null_mkt, leaky):
    r = future_blind(null_mkt, Strategy("positions", leaky))
    assert r.result == "REJECT" and r.evidence["mismatches"]


# ---- backtest and costs ---------------------------------------------------------------------------
def test_backtest_passes_real_edge_and_rejects_null(edge_mkt, null_mkt):
    assert backtest(edge_mkt, Strategy("positions", fade)).result == "PASS"
    assert backtest(null_mkt, Strategy("positions", fade)).result == "REJECT"


def test_costs_rejects_a_small_edge_that_cannot_pay_the_spread():
    small = market(n_days=250, seed=5, edge=0.2)
    r = costs(small, Strategy("positions", fade))
    assert r.result == "REJECT"
    assert 0 < r.evidence["breakeven_spread_usd"] < 0.5  # real but too small
    assert r.evidence["net_mean_by_spread"]["0.00"] > 0 > r.evidence["net_mean_by_spread"]["0.50"]


def test_costs_breakeven_in_r_for_brackets(edge_mkt):
    r = costs(edge_mkt, Strategy("brackets", bracket_fade))
    assert r.evidence["unit"] == "R per trade" and r.evidence["breakeven_spread_usd"] > 0


# ---- random entry -----------------------------------------------------------------------------------
def test_random_entry_separates_real_entries_from_luck(edge_mkt, null_mkt):
    assert random_entry(edge_mkt, Strategy("positions", fade), runs=200).result == "PASS"
    assert random_entry(null_mkt, Strategy("positions", fade), runs=200).result == "REJECT"
    assert random_entry(null_mkt, Strategy("brackets", bracket_fade), runs=100).result == "REJECT"


# ---- multiple testing -------------------------------------------------------------------------------
def test_expected_max_sharpe_grows_with_trials():
    assert expected_max_sharpe(1, 0.01) == 0
    assert 0 < expected_max_sharpe(10, 0.01) < expected_max_sharpe(1000, 0.01)


def test_deflated_sharpe_discounts_the_best_of_many_null_strategies():
    rng = np.random.default_rng(0)
    trials = rng.normal(0, 1, (250, 200))
    best = trials[:, np.argmax(trials.mean(0) / trials.std(0))]
    assert deflated_sharpe(best, n_trials=1)["dsr"] > 0.95  # looks great alone
    assert deflated_sharpe(best, n_trials=200)["dsr"] < 0.95  # not after 200 tries
    real = rng.normal(0.4, 1, 250)  # a genuinely strong daily Sharpe survives the same deflation
    assert deflated_sharpe(real, n_trials=200)["dsr"] > 0.95


def test_pbo_is_high_on_noise_and_low_with_a_dominant_config():
    # On pure noise the in-sample winner's out-of-sample rank is uniform, so PBO averages ~0.5.
    # (One dataset's splits are strongly correlated, so a single draw is noisy; average several.)
    draws = [pbo_cscv(np.random.default_rng(s).normal(0, 1, (480, 30)), n_blocks=10)["pbo"] for s in range(8)]
    assert 0.3 < float(np.mean(draws)) < 0.7
    noise = np.random.default_rng(1).normal(0, 1, (480, 30))
    good = noise.copy()
    good[:, 7] += 0.4
    assert pbo_cscv(good, n_blocks=10)["pbo"] < 0.1


def test_multiple_test_needs_a_recorded_trial_count(null_mkt):
    assert multiple_test(null_mkt, Strategy("positions", fade), n_trials=None).result == "INFO"
    grid = [{"k": k, "h": h} for k in (2.0, 2.5, 3.0) for h in (3, 6, 12)]
    r = multiple_test(null_mkt, Strategy("positions", fade, grid[4]), n_trials=len(grid), grid=grid)
    assert r.result == "REJECT" and "pbo" in r.evidence


# ---- stability and sessions -----------------------------------------------------------------------------
def test_stability_and_sessions(edge_mkt, null_mkt):
    assert stability(edge_mkt, Strategy("positions", fade)).result == "PASS"
    assert stability(null_mkt, Strategy("positions", fade)).result == "REJECT"
    s = sessions(edge_mkt, Strategy("positions", fade))
    assert s.result == "INFO" and set(s.evidence["by_session"]) <= {
        "asia",
        "london",
        "newyork",
        "late",
        "off",
    }


def test_dropping_trades_open_at_the_end_is_censoring_not_a_leak(edge_mkt):
    """Found on the case study: the harness reports completed trades only, so a signal on the final bar vanishes."""

    def completed_only(bars, p):
        out = bracket_fade(bars, p)
        last = bars.index[-1]
        return [
            b for b in out if b.ts < last - pd.Timedelta(minutes=5 * 10)
        ]  # still open at the end -> dropped

    assert future_blind(edge_mkt, Strategy("brackets", completed_only)).result == "PASS"

    def peeking(bars, p):  # a bracket leak must still fail: the stop uses the next bar's range
        rng_next = (bars["high"] - bars["low"]).shift(-1)
        return [
            Bracket(
                b.ts,
                b.side,
                float(
                    b.stop_usd + rng_next.get(b.ts, 0)
                    if rng_next.get(b.ts) == rng_next.get(b.ts)
                    else b.stop_usd
                ),
            )
            for b in bracket_fade(bars, p)
        ]

    assert future_blind(edge_mkt, Strategy("brackets", peeking)).result == "REJECT"
