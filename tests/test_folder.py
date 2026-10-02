"""Auditing your own folder: data sources, explicit costs, confinement, and the shipped examples."""

from __future__ import annotations

import json
import shutil

import numpy as np
import pandas as pd
import pytest

from skeptic import config
from skeptic.cli import main as cli
from skeptic.folder import FolderError, StrategyFolder, _spread_ladder
from skeptic.synth import market

EX = config.ROOT / "examples"


def _folder(tmp_path, data: dict, spread: float | None = 0.5, extra: dict | None = None):
    d = tmp_path / "strat"
    d.mkdir(exist_ok=True)
    shutil.copy(EX / "fade_clean" / "strategy.py", d / "strategy.py")
    meta = {"params": {"k": 3.0, "span": 100, "hold": 6}, "data": data, **(extra or {})}
    if spread is not None:
        meta["spread_usd"] = spread
    (d / "params.json").write_text(json.dumps(meta))
    return d


# ---- the examples are what the README promises ----------------------------------------------------
def test_clean_example_survives_and_leaky_example_is_caught():
    clean, leaky = StrategyFolder(EX / "fade_clean"), StrategyFolder(EX / "fade_leaky")
    for name in ("future_blind", "backtest", "costs", "random_entry", "stability"):
        assert clean.run(name)["result"] == "PASS", name
    assert leaky.run("future_blind")["result"] == "REJECT"
    # the leak flatters every other number: that is why the probe exists
    assert leaky.run("backtest")["evidence"]["mean"] > clean.run("backtest")["evidence"]["mean"]


def test_results_carry_provenance_and_are_cached():
    f = StrategyFolder(EX / "fade_clean")
    r = f.run("backtest")
    p = r["provenance"]
    assert p["spread_usd"] == 0.5 and p["data"]["source"] == "synthetic" and p["data"]["bars"] > 10_000
    assert "edge" not in p["data"]  # a planted edge is never echoed back
    assert any("Synthetic market" in c for c in r["caveats"])
    assert f.run("backtest") is r


# ---- costs are explicit -----------------------------------------------------------------------------
def test_file_source_requires_a_spread(tmp_path):
    bars = market(n_days=20, seed=1)
    d = _folder(tmp_path, {"source": "file", "path": "bars.csv"}, spread=None)
    bars[["open", "high", "low", "close"]].rename_axis("ts").to_csv(d / "bars.csv")
    with pytest.raises(FolderError, match="spread_usd"):
        StrategyFolder(d).run("backtest")


def test_zero_spread_is_refused(tmp_path):
    d = _folder(tmp_path, {"source": "synthetic", "seed": 1, "n_days": 20}, spread=0.0)
    with pytest.raises(FolderError, match="never zero"):
        StrategyFolder(d).spread()


def test_default_spread_is_stated_as_an_assumption(tmp_path):
    d = _folder(tmp_path, {"source": "synthetic", "seed": 1, "n_days": 20}, spread=None)
    r = StrategyFolder(d).run("backtest")
    assert r["provenance"]["spread_usd"] == config.REALISTIC_SPREAD_USD
    assert any("No spread_usd" in c for c in r["caveats"])


def test_fx_scale_spread_ladder_keeps_distinct_keys(tmp_path):
    assert _spread_ladder(0.0001) == (0.00004, 0.0001, 0.00018)
    d = _folder(tmp_path, {"source": "synthetic", "seed": 1, "n_days": 60}, spread=0.0001)
    table = StrategyFolder(d).run("costs")["evidence"]["net_mean_by_spread"]
    assert len(table) == 4


# ---- file data: parsed, labelled, confined --------------------------------------------------------
def test_csv_bars_get_sessions_and_trading_days(tmp_path):
    bars = market(n_days=20, seed=2)
    d = _folder(tmp_path, {"source": "file", "path": "bars.csv"})
    bars[["open", "high", "low", "close"]].rename_axis("ts").to_csv(d / "bars.csv")
    b = StrategyFolder(d).bars()
    assert str(b.index.tz) == "UTC" and {"session", "trading_day"} <= set(b.columns)
    assert len(b) == len(bars)


def test_data_file_must_be_inside_the_folder(tmp_path):
    outside = tmp_path / "elsewhere.csv"
    pd.DataFrame({"ts": [0], "open": [1], "high": [1], "low": [1], "close": [1]}).to_csv(outside)
    d = _folder(tmp_path, {"source": "file", "path": "../elsewhere.csv"})
    with pytest.raises(FolderError, match="inside the strategy folder"):
        StrategyFolder(d).bars()


def test_bench_manifest_is_unreachable(tmp_path):
    d = _folder(tmp_path, {"source": "file", "path": str(config.ROOT / "bench" / "manifest.json")})
    with pytest.raises(PermissionError, match="manifest"):
        StrategyFolder(d).bars()


def test_bench_cases_cannot_be_run_without_their_hidden_market():
    with pytest.raises(FolderError, match='"data" entry'):
        StrategyFolder(config.ROOT / "bench" / "cases" / "case_01").run("backtest")


def test_editing_the_strategy_invalidates_the_cache(tmp_path):
    d = _folder(tmp_path, {"source": "synthetic", "seed": 3, "n_days": 60})
    f = StrategyFolder(d)
    first = f.run("future_blind")["result"]
    src = (d / "strategy.py").read_text().replace(".shift(1)", ".shift(-1)")
    (d / "strategy.py").write_text(src)
    assert first == "PASS" and f.run("future_blind")["result"] == "REJECT"


def test_too_little_data_is_an_error(tmp_path):
    d = _folder(tmp_path, {"source": "file", "path": "bars.csv"})
    idx = pd.date_range("2024-01-01", periods=100, freq="5min", tz="UTC")
    px = 2000 + np.arange(100.0)
    pd.DataFrame({"open": px, "high": px + 1, "low": px - 1, "close": px}, index=idx).rename_axis(
        "ts"
    ).to_csv(d / "bars.csv")
    with pytest.raises(FolderError, match="at least 500"):
        StrategyFolder(d).bars()


# ---- CLI exit codes ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("folder", "check", "code"),
    [("fade_clean", "future_blind", 0), ("fade_leaky", "future_blind", 1), ("missing", "backtest", 2)],
)
def test_cli_exit_codes(folder, check, code, capsys):
    with pytest.raises(SystemExit) as e:
        cli(["check", str(EX / folder), check])
    assert e.value.code == code
