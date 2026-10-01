"""XAUUSD case-study data: public 1-minute bars -> 5-minute and 1-hour UTC bars with session labels.

    python -m skeptic.data            # download (~150 MB) if needed, then build data/xauusd_bars.parquet

The raw files are never committed (see .gitignore); this module rebuilds everything from the mirror.
"""

from __future__ import annotations

import sys
import urllib.request

import numpy as np
import pandas as pd

from skeptic import config

BAR_RULES = {"5min": "5min", "1h": "1h"}


def download(force: bool = False) -> list[str]:
    config.XAU_RAW_DIR.mkdir(parents=True, exist_ok=True)
    got = []
    for name in config.XAU_FILES:
        dest = config.XAU_RAW_DIR / name
        if dest.exists() and not force:
            continue
        url = f"https://huggingface.co/datasets/{config.XAU_HF_REPO}/resolve/main/{name}"
        tmp = dest.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.rename(dest)
        got.append(name)
    return got


def read_m1() -> pd.DataFrame:
    """All 1-minute bid bars, UTC-indexed, de-duplicated and sorted."""
    frames = []
    for name in config.XAU_FILES:
        df = pd.read_csv(
            config.XAU_RAW_DIR / name,
            header=None,
            names=["d", "t", "open", "high", "low", "close", "vol"],
            dtype={"d": str, "t": str},
        )
        ts = pd.to_datetime(df["d"] + " " + df["t"], format="%Y.%m.%d %H:%M")
        local = pd.DatetimeIndex(ts).tz_localize(config.HISTDATA_TZ, ambiguous="NaT", nonexistent="NaT")
        df.index = local.tz_convert("UTC")
        frames.append(df.loc[~df.index.isna(), ["open", "high", "low", "close"]])  # DST-ambiguous minutes dropped
    m1 = pd.concat(frames)
    m1 = m1[~m1.index.duplicated(keep="first")].sort_index()
    return m1


def session_of(hour_close: np.ndarray) -> np.ndarray:
    """Session label from the UTC hour in which a bar closes (decision time)."""
    out = np.full(hour_close.shape, "off", dtype=object)
    for name, (a, b) in config.SESSIONS.items():
        mask = (hour_close >= a) | (hour_close < b) if a > b else (hour_close >= a) & (hour_close < b)
        out[mask] = name
    return out


def resample(m1: pd.DataFrame, rule: str) -> pd.DataFrame:
    """OHLC bars labelled by their open time; only intervals that contain at least one minute are kept."""
    agg = m1.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    )
    agg["minutes"] = m1["close"].resample(rule, label="left", closed="left").count()
    agg = agg[agg["minutes"] > 0].copy()
    close_time = agg.index + pd.Timedelta(rule)
    agg["session"] = session_of(close_time.hour.to_numpy())  # a bar belongs where its close falls
    # CME convention: the trading day rolls at 17:00 New York, so +7h maps the roll to midnight.
    agg["trading_day"] = (agg.index.tz_convert(config.HISTDATA_TZ) + pd.Timedelta(hours=7)).date
    return agg


def build() -> pd.DataFrame:
    m1 = read_m1()
    parts = []
    for tf, rule in BAR_RULES.items():
        bars = resample(m1, rule)
        bars.insert(0, "tf", tf)
        parts.append(bars)
    out = pd.concat(parts).reset_index(names="ts")
    out.to_parquet(config.XAU_BARS, index=False)
    return out


def load_bars(tf: str = "5min") -> pd.DataFrame:
    """Bars for one timeframe, indexed by UTC open time."""
    df = pd.read_parquet(config.XAU_BARS)
    df = df[df["tf"] == tf].drop(columns="tf").set_index("ts")
    return df


def main() -> None:
    got = download()
    print(f"downloaded {len(got)} file(s)", file=sys.stderr)
    out = build()
    for tf, g in out.groupby("tf"):
        print(f"{tf}: {len(g):,} bars, {g['ts'].min()} -> {g['ts'].max()}", file=sys.stderr)


if __name__ == "__main__":
    main()
