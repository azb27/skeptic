"""The XAUUSD feed is converted to UTC correctly and labelled the way the case study expects."""

from __future__ import annotations

import numpy as np
import pytest

from skeptic import config
from skeptic.data import load_bars, session_of

needs_data = pytest.mark.skipif(not config.XAU_BARS.exists(), reason="run `python -m skeptic.data` first")


def test_session_labels_by_close_hour():
    hours = np.array([23, 0, 6, 7, 11, 12, 20, 21, 22])
    assert session_of(hours).tolist() == [
        "asia", "asia", "asia", "london", "london", "newyork", "newyork", "late", "off",
    ]  # fmt: skip


@needs_data
def test_daily_break_follows_new_york_time_through_daylight_saving():
    """The break is 17:00-18:00 New York: 22:00 UTC in winter, 21:00 UTC in summer."""
    b = load_bars("1h")
    winter = b[b.index.month == 1].index.hour.value_counts()
    summer = b[b.index.month == 7].index.hour.value_counts()
    assert winter.get(22, 0) < 0.1 * winter[12] and winter.get(21, 0) > 0.5 * winter[12]
    assert summer.get(21, 0) < 0.1 * summer[12] and summer.get(22, 0) > 0.5 * summer[12]


@needs_data
def test_bars_are_consistent_ohlc_and_sorted():
    b = load_bars("5min")
    assert b.index.is_monotonic_increasing and not b.index.has_duplicates
    assert (b["high"] >= b[["open", "close"]].max(axis=1)).all()
    assert (b["low"] <= b[["open", "close"]].min(axis=1)).all()
    assert str(b.index.tz) == "UTC"
