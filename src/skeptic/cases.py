"""Load a strategy case folder (strategy.py + params.json) into a `Strategy` the checks can run."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from skeptic.checks import Strategy


def load_strategy(case_dir: Path | str) -> Strategy:
    case_dir = Path(case_dir)
    path = case_dir / "strategy.py"
    name = f"skeptic_case_{abs(hash(str(case_dir.resolve())))}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    meta = read_params(case_dir)
    if hasattr(mod, "signals"):
        return Strategy(
            "brackets",
            mod.signals,
            meta.get("params", {}),
            meta.get("max_bars", 41),
            meta.get("entry", "close"),
        )
    if hasattr(mod, "positions"):
        return Strategy("positions", mod.positions, meta.get("params", {}))
    raise AttributeError(f"{path} defines neither positions() nor signals()")


def read_params(case_dir: Path | str) -> dict:
    p = Path(case_dir) / "params.json"
    return json.loads(p.read_text()) if p.exists() else {}
