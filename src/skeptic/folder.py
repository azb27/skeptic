"""A strategy folder anyone can audit: their code, their notes, and a declared data source and spread.

Used by the MCP server and the `skeptic audit` CLI (the bench uses its own runner, with the market spec
held in the manifest). A folder holds `strategy.py` (positions() or signals(), see SPEC §3) and
`params.json`, which declares where the bars come from:

    {"params": {...},
     "data": {"source": "xauusd", "timeframe": "5min", "start": "2024-01-01", "end": "2026-01-31"},
     "spread_usd": 0.5,
     "n_trials": 12, "grid": [...]}            # optional: how many configurations were tried

Data sources:
    xauusd     the public 1-minute XAUUSD mirror, as 5min or 1h bars (`python -m skeptic.data` first)
    file       a CSV or Parquet file inside the folder: ts, open, high, low, close (UTC timestamps,
               bar open time); optional trading_day and session columns
    synthetic  a seeded synthetic market (seed, n_days, edge): for trying Skeptic without downloads

Costs are explicit (CLAUDE.md rule 3): the spread is never zero by default. XAUUSD-scale sources default
to the realistic $0.50 with a caveat saying so; a file source must declare `spread_usd`.

The folder's strategy.py is imported and executed, as any backtest would. Nothing here writes to the
folder, and the bench manifest can never be read through it.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from skeptic import __version__, checks, config
from skeptic.cases import load_strategy
from skeptic.data import load_bars, session_of
from skeptic.synth import market

CHECKS = ("future_blind", "backtest", "costs", "random_entry", "multiple_test", "stability", "sessions")
MANIFEST = config.ROOT / "bench" / "manifest.json"
XAU_SCALE = {"xauusd", "synthetic"}
OHLC = ["open", "high", "low", "close"]


class FolderError(ValueError):
    """A problem with the folder the user can fix (missing file, bad data spec, no spread)."""


def _guard(p: Path) -> Path:
    if p.resolve() == MANIFEST.resolve():
        raise PermissionError("the bench manifest is ground truth and is not readable here")
    return p


@dataclass
class StrategyFolder:
    root: Path
    _bars: pd.DataFrame | None = field(default=None, repr=False)
    _bars_key: str | None = field(default=None, repr=False)
    _cache: dict[tuple, dict] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root).expanduser().resolve()
        if not self.root.is_dir():
            raise FolderError(f"{self.root} is not a folder")
        if not (self.root / "strategy.py").is_file():
            raise FolderError(f"{self.root} has no strategy.py (see SPEC §3 for the contract)")

    # ---- declared metadata ----------------------------------------------------------------------
    @property
    def meta(self) -> dict[str, Any]:
        p = self.root / "params.json"
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError as e:
            raise FolderError(f"params.json is not valid JSON: {e}") from e

    def data_spec(self) -> dict[str, Any]:
        spec = self.meta.get("data")
        if not isinstance(spec, dict) or "source" not in spec:
            raise FolderError(
                'params.json needs a "data" entry, e.g. {"source": "xauusd", "timeframe": "5min"}, '
                '{"source": "file", "path": "bars.csv"} or {"source": "synthetic", "seed": 1}'
            )
        if spec["source"] not in ("xauusd", "file", "synthetic"):
            raise FolderError(f"unknown data source {spec['source']!r}")
        return spec

    def spread(self) -> tuple[float, list[str]]:
        """(round-trip spread in price units, caveats)."""
        s = self.meta.get("spread_usd")
        if s is not None:
            s = float(s)
            if s <= 0:
                raise FolderError("spread_usd must be positive: costs are never zero")
            return s, []
        if self.data_spec()["source"] in XAU_SCALE:
            return config.REALISTIC_SPREAD_USD, [
                f"No spread_usd in params.json: assumed ${config.REALISTIC_SPREAD_USD:.2f} round trip "
                "(a realistic XAUUSD retail spread). Set spread_usd for your broker."
            ]
        raise FolderError("a file data source must declare spread_usd in params.json (costs are explicit)")

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        for name in ("strategy.py", "params.json"):
            p = self.root / name
            if p.exists():
                h.update(p.read_bytes())
        spec = self.meta.get("data") or {}
        if spec.get("source") == "file" and spec.get("path"):
            p = self.root / spec["path"]
            if p.exists():
                st = p.stat()
                h.update(f"{st.st_size}:{st.st_mtime_ns}".encode())
        return h.hexdigest()[:16]

    # ---- data -----------------------------------------------------------------------------------
    def bars(self) -> pd.DataFrame:
        spec = self.data_spec()
        key = json.dumps(spec, sort_keys=True) + self.fingerprint()
        if self._bars is None or self._bars_key != key:
            self._bars, self._bars_key = self._load(spec), key
        return self._bars

    def _load(self, spec: dict[str, Any]) -> pd.DataFrame:
        src = spec["source"]
        if src == "synthetic":
            allowed = {"seed", "n_days", "edge", "base_vol", "drift"}
            kw = {k: v for k, v in spec.items() if k in allowed}
            return market(**kw)
        if src == "xauusd":
            if not config.XAU_BARS.exists():
                raise FolderError(
                    "XAUUSD bars not built yet: run `python -m skeptic.data` (~150 MB download)"
                )
            tf = spec.get("timeframe", "5min")
            if tf not in ("5min", "1h"):
                raise FolderError("xauusd timeframe must be 5min or 1h")
            b = load_bars(tf)
            if spec.get("start"):
                b = b[b.index >= pd.Timestamp(spec["start"], tz="UTC")]
            if spec.get("end"):
                b = b[b.index < pd.Timestamp(spec["end"], tz="UTC")]
            return b
        return self._load_file(spec)

    def _load_file(self, spec: dict[str, Any]) -> pd.DataFrame:
        rel = spec.get("path")
        if not rel:
            raise FolderError('a file data source needs "path"')
        p = _guard(self.root / rel)
        rp = p.resolve()
        if self.root not in rp.parents or p.is_symlink() or not rp.is_file():
            raise FolderError(f"{rel}: the data file must be a regular file inside the strategy folder")
        df = pd.read_parquet(rp) if rp.suffix == ".parquet" else pd.read_csv(rp)
        if "ts" in df.columns:
            df = df.set_index("ts")
        missing = [c for c in OHLC if c not in df.columns]
        if missing:
            raise FolderError(f"{rel} is missing columns {missing}; need ts, open, high, low, close")
        idx = pd.to_datetime(df.index, utc=True)
        df = df.set_axis(idx).sort_index()
        df = df[~df.index.duplicated(keep="first")]
        if len(df) < 500:
            raise FolderError(f"{rel} has {len(df)} bars; the checks need at least 500")
        step = pd.Series(df.index).diff().median()
        if "session" not in df.columns:
            df["session"] = session_of((df.index + step).hour.to_numpy())
        if "trading_day" not in df.columns:
            df["trading_day"] = df.index.date
        return df

    # ---- checks ---------------------------------------------------------------------------------
    def describe(self) -> dict[str, Any]:
        """What Skeptic would audit: files, contract, data, spread. Loads the data; runs no check."""
        files = sorted(
            str(p.relative_to(self.root))
            for p in self.root.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and not p.name.startswith(".")
        )
        meta = self.meta
        strat = load_strategy(self.root)
        b = self.bars()
        spread, cav = self.spread()
        return {
            "result": "INFO",
            "evidence": {
                "files": files,
                "contract": "positions() with next-bar-open fills"
                if strat.kind == "positions"
                else f"signals() brackets, entry at {strat.entry}, timeout {strat.max_bars} bars",
                "params": meta.get("params", {}),
                "n_trials": meta.get("n_trials"),
                "grid_logged": bool(meta.get("grid")),
                "data": self._data_summary(b),
                "spread_usd": spread,
                "checks": list(CHECKS),
            },
            "caveats": cav + self._data_caveats(),
        }

    def _data_summary(self, b: pd.DataFrame) -> dict[str, Any]:
        step = pd.Series(b.index).diff().median()
        return {
            **{k: v for k, v in self.data_spec().items() if k != "edge"},  # never echo a planted edge
            "bars": len(b),
            "first": str(b.index[0]),
            "last": str(b.index[-1]),
            "bar": str(step),
            "trading_days": int(pd.Series(b["trading_day"]).nunique()),
        }

    def _data_caveats(self) -> list[str]:
        src = self.data_spec()["source"]
        if src == "synthetic":
            return ["Synthetic market (seeded): results say nothing about real prices."]
        if src == "xauusd":
            return ["Prices are a public 1-minute XAUUSD bid feed; broker prices differ in spread and gaps."]
        return []

    def run(self, name: str, n_trials: int | None = None) -> dict[str, Any]:
        """One check, cached on (check, n_trials, folder contents). Returns {result, evidence, caveats, provenance}."""
        if name not in CHECKS:
            raise FolderError(f"unknown check {name!r}; one of {', '.join(CHECKS)}")
        key = (name, n_trials, self.fingerprint())
        if key in self._cache:
            return self._cache[key]
        bars = self.bars()
        strat = load_strategy(self.root)
        spread, cav = self.spread()
        meta = self.meta
        t0 = time.perf_counter()
        if name == "future_blind":
            r = checks.future_blind(bars, strat)
        elif name == "costs":
            r = checks.costs(bars, strat, realistic_usd=spread, spreads=_spread_ladder(spread))
        elif name == "multiple_test":
            n = n_trials if n_trials is not None else meta.get("n_trials")
            r = checks.multiple_test(bars, strat, n_trials=n, grid=meta.get("grid"), spread_usd=spread)
            if r.result == "INFO" and n is None:
                r.caveats.append("Pass n_trials (from the research notes) to run the deflation.")
        else:
            r = checks.ALL[name](bars, strat, spread_usd=spread)
        out = r.to_dict()
        out.pop("name", None)
        out["caveats"] = [*cav, *self._data_caveats(), *out.get("caveats", [])]
        out["provenance"] = {
            "check": name,
            "folder": str(self.root),
            "fingerprint": self.fingerprint(),
            "data": self._data_summary(bars),
            "spread_usd": spread,
            "engine": "positions: fills at the next bar's open"
            if strat.kind == "positions"
            else "brackets: ambiguous bars count as stops",
            "seed": config.SEED,
            "skeptic": __version__,
            "seconds": round(time.perf_counter() - t0, 2),
        }
        self._cache[key] = out
        return out


def _spread_ladder(spread: float) -> tuple[float, ...]:
    """The costs check reports net expectancy at 0.4x, 1x and 1.8x the declared spread ($0.20/$0.50/$0.90 for gold)."""
    return tuple(float(f"{spread * m:.4g}") for m in (0.4, 1.0, 1.8))


_FOLDERS: dict[Path, StrategyFolder] = {}


def open_folder(path: str | Path) -> StrategyFolder:
    """One StrategyFolder per path per process, so repeated checks reuse loaded bars and results."""
    root = Path(path).expanduser().resolve()
    if root not in _FOLDERS:
        _FOLDERS[root] = StrategyFolder(root)
    return _FOLDERS[root]
