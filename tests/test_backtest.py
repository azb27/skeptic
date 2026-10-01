"""Both engines, checked against trades computed by hand."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from skeptic.backtest import Bracket, clustered_mean_ci, run_brackets, run_positions, summarize


def bars_from(rows: list[tuple[float, float, float, float]], days: list[int] | None = None) -> pd.DataFrame:
    idx = pd.date_range("2024-01-02 08:00", periods=len(rows), freq="5min", tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    df["trading_day"] = days if days is not None else [0] * len(rows)
    return df


# ---- position engine -----------------------------------------------------------------------------
def test_positions_execute_at_next_open_and_pay_one_round_trip():
    b = bars_from([(100, 101, 99, 100), (101, 103, 100, 102), (102, 104, 101, 103), (105, 106, 104, 105)])
    pos = pd.Series([1, 1, 0, 0], index=b.index)  # long decided at bar 0 close, flat decided at bar 2 close
    t = run_positions(b, pos, spread_usd=0.5)
    assert len(t) == 1
    row = t.iloc[0]
    assert row.entry_px == 101 and row.exit_px == 105  # bar 1 open in, bar 3 open out
    assert row.gross_usd == 4 and row.net_usd == pytest.approx(3.5)


def test_flip_is_two_trades_and_a_position_decided_on_the_last_bar_is_never_filled():
    b = bars_from([(100, 0, 0, 0), (101, 0, 0, 0), (99, 0, 0, 0), (97, 0, 0, 0)])
    t = run_positions(b, pd.Series([1, -1, -1, 1], index=b.index), spread_usd=0.2)
    assert t["side"].tolist() == [1, -1]
    assert t["gross_usd"].tolist() == [-2.0, 2.0]  # long 101->99, short 99->97 (closed at the last open)
    assert t["net_usd"].sum() == pytest.approx(0.0 - 0.4)


def test_position_signal_cannot_trade_on_its_own_bar():
    b = bars_from([(100, 110, 90, 109), (109, 110, 108, 109)])
    t = run_positions(b, pd.Series([1, 0], index=b.index), spread_usd=0.0)
    assert t.empty or t.iloc[0].entry_px == 109  # the bar-0 rally is never captured


# ---- bracket engine ------------------------------------------------------------------------------
def test_bracket_target_stop_and_costs_in_r():
    b = bars_from([(100, 100, 100, 100), (100, 102.5, 99.5, 102), (102, 103, 101, 102)])
    win = run_brackets(b, [Bracket(b.index[0], +1, stop_usd=2.0)], spread_usd=0.5)
    assert win.iloc[0].outcome == "target" and win.iloc[0].gross_r == 1.0
    assert win.iloc[0].net_r == pytest.approx(1 - 0.25)
    lose = run_brackets(b, [Bracket(b.index[0], -1, stop_usd=2.0)], spread_usd=0.5)
    assert lose.iloc[0].outcome == "stop" and lose.iloc[0].net_r == pytest.approx(-1.25)


def test_ambiguous_bar_is_pessimistic_by_default():
    b = bars_from([(100, 100, 100, 100), (100, 103, 97, 100)])  # touches both 102 and 98
    s = [Bracket(b.index[0], +1, stop_usd=2.0)]
    assert run_brackets(b, s, 0.0).iloc[0].outcome == "ambiguous_stop"
    assert run_brackets(b, s, 0.0, ambiguity="optimistic").iloc[0].outcome == "ambiguous_target"


def test_timeout_exits_at_close_and_entry_bar_is_not_used_for_exits():
    b = bars_from([(100, 150, 50, 100), (100, 101, 99.5, 100.5), (100.5, 101, 100, 100.8)])
    t = run_brackets(b, [Bracket(b.index[0], +1, stop_usd=5.0)], 0.0, max_bars=2)
    assert t.iloc[0].outcome == "timeout"
    assert t.iloc[0].gross_r == pytest.approx(0.8 / 5)


def test_bad_arguments_fail_loudly():
    b = bars_from([(100, 100, 100, 100)] * 3)
    with pytest.raises(ValueError):
        run_brackets(b, [Bracket(b.index[0], 1, 0.0)], 0.5)
    with pytest.raises(ValueError):
        run_brackets(b, [], 0.5, entry="magic")


# ---- statistics --------------------------------------------------------------------------------------
def test_clustered_ci_is_wider_than_naive_when_trades_cluster():
    rng = np.random.default_rng(0)
    day_effect = np.repeat(rng.normal(0, 1, 50), 20)  # 50 days x 20 correlated trades
    v = day_effect + rng.normal(0, 0.2, 1000)
    days = np.repeat(np.arange(50), 20)
    _, lo_c, hi_c = clustered_mean_ci(v, days)
    _, lo_n, hi_n = clustered_mean_ci(v, np.arange(1000))
    assert (hi_c - lo_c) > 2 * (hi_n - lo_n)


def test_summarize_reports_counts_and_drawdown():
    t = pd.DataFrame({"net_r": [1, -1, -1, 2], "trading_day": [0, 0, 1, 1]})
    s = summarize(t, "net_r")
    assert s["trades"] == 4 and s["days"] == 2 and s["mean"] == pytest.approx(0.25)
    assert s["max_drawdown"] == pytest.approx(2.0) and s["hit_rate"] == 0.5


def test_sharpe_counts_days_without_trades_when_told_about_them():
    t = pd.DataFrame({"net_r": [1.0, 1.2, 0.8], "trading_day": [0, 5, 9]})
    busy = summarize(t, "net_r")["sharpe_daily_ann"]
    honest = summarize(t, "net_r", all_days=range(10))["sharpe_daily_ann"]
    assert honest < busy / 3  # seven flat days dilute a strategy that rarely trades
