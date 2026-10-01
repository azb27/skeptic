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
def test_daily_break_sits_at_22_utc_so_the_offset_is_right():
    b = load_bars("1h")
    by_hour = b.index.hour.value_counts()
    assert by_hour.get(22, 0) < 0.1 * by_hour[12]  # the 17:00-18:00 EST break, i.e. 22:00 UTC


@needs_data
def test_bars_are_consistent_ohlc_and_sorted():
    b = load_bars("5min")
    assert b.index.is_monotonic_increasing and not b.index.has_duplicates
    assert (b["high"] >= b[["open", "close"]].max(axis=1)).all()
    assert (b["low"] <= b[["open", "close"]].min(axis=1)).all()
    assert str(b.index.tz) == "UTC"
