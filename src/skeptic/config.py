"""Single source of truth for paths, market conventions and check thresholds."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("SKEPTIC_DATA_DIR", ROOT / "data"))
RUNS_DIR = ROOT / "runs"

# ---- XAUUSD case-study data ---------------------------------------------------------------------
# HistData-format 1-minute bid bars, mirrored publicly on Hugging Face. HistData documents its timestamps
# as EST without daylight saving, but this feed's daily 17:00-18:00 break sits at 17:00 in file time in
# both January and July, so the timestamps follow New York local time (with DST). We trust the data.
XAU_HF_REPO = "fokan/xauusd-2009-2026"
XAU_FILES = [f"DAT_MT_XAUUSD_M1_{y}.csv" for y in range(2020, 2026)] + ["DAT_MT_XAUUSD_M1_202601.csv"]
XAU_RAW_DIR = DATA_DIR / "xauusd_m1"
XAU_BARS = DATA_DIR / "xauusd_bars.parquet"  # M1 -> 5m and 1h, UTC, with session labels
HISTDATA_TZ = "America/New_York"

# Sessions by UTC hour of the bar's close. The daily break is 17:00-18:00 New York (21:00 or 22:00 UTC).
SESSIONS = {"asia": (23, 7), "london": (7, 12), "newyork": (12, 21), "late": (21, 22)}

# ---- costs ---------------------------------------------------------------------------------------
# Round-trip spread in USD per ounce. $0.50 is the deciding column in Aziz's pre-registration;
# $0.20 and $0.90 bracket it.
SPREADS_USD = (0.20, 0.50, 0.90)
REALISTIC_SPREAD_USD = 0.50

# ---- checks --------------------------------------------------------------------------------------
SEED = 27
N_BOOT = 2000
FUTURE_BLIND_CUTS = 5
FUTURE_BLIND_DECISION_CUTS = 25  # extra cuts placed exactly at bars where the strategy's decision changes
RANDOM_ENTRY_RUNS = 500
DSR_THRESHOLD = 0.95
PBO_THRESHOLD = 0.5

# ---- agent (P4) ----------------------------------------------------------------------------------
MODEL = os.environ.get("SKEPTIC_MODEL", "claude-sonnet-5")
CHEAP_MODEL = os.environ.get("SKEPTIC_CHEAP_MODEL", "claude-haiku-4-5-20251001")
