"""Build the Skeptic bench: strategy cases with planted flaws and planted edges, plus the ground-truth manifest.

    python -m bench.build            # writes bench/cases/case_XX/ and bench/manifest.json (deterministic)

Ground truth is set by construction and then confirmed by an oracle:
- every SURVIVES case must pass all checks on its market;
- every "no edge" case must fail the backtest;
- every multiple-testing case must look good alone (pass the backtest) yet fail deflation;
- every cost case must be gross-positive and fail the cost check.
A case that doesn't confirm is re-seeded. Leak cases are REJECT by construction, whatever the probe says.
The manifest records whether `future_blind` caught each leak, for the analysis.

The manifest is ground truth: only tests/ and evals/ may read it, never the agent's tools.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from bench.templates import FILTER_ON, HTF_CLEAN, KIND, LEAKS, TEMPLATES
from skeptic import checks
from skeptic.cases import load_strategy
from skeptic.synth import market

ROOT = Path(__file__).resolve().parent
CASES = ROOT / "cases"
MANIFEST = ROOT / "manifest.json"
SEED = 2027
N_DAYS = 400


# ---------------------------------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------------------------------
def _fill(tpl: str, overrides: dict[str, str] | None, htf: bool) -> str:
    src, slots = TEMPLATES[tpl]
    fill = dict(slots)
    key = tpl if tpl in HTF_CLEAN else tpl.rstrip("0123456789")
    if htf and key in HTF_CLEAN:
        fill["HTF"] = HTF_CLEAN[key]
        fill["FILTER"] = FILTER_ON[key]
    fill.update(overrides or {})
    out = src
    for slot, code in fill.items():
        out = out.replace(f"<<{slot}>>\n", (code + "\n") if code else "")
    assert "<<" not in out, f"unfilled slot in {tpl}"
    return out


def render(tpl: str, overrides: dict[str, str] | None = None, htf: bool = False) -> tuple[str, int | None]:
    """Fill a template. Returns (source, 1-based line where it first differs from the clean version)."""
    out = _fill(tpl, overrides, htf)
    if not overrides:
        return out, None
    clean = _fill(tpl, None, htf).splitlines()
    lines = out.splitlines()
    line = next(
        (i + 1 for i, (a, b) in enumerate(zip(lines, clean, strict=False)) if a != b),
        min(len(lines), len(clean)) + 1,
    )
    return out, line


# ---------------------------------------------------------------------------------------------------
# research logs (what a researcher would hand over with the code)
# ---------------------------------------------------------------------------------------------------
LOG_HONEST = """# Research notes

- Idea: {idea}
- Parameters are round values chosen before the first backtest and not changed afterwards: {params}.
- Backtested on {n_days} trading days of 5-minute bars, positions filled at the next bar's open.
"""

LOG_LEAK = """# Research notes

- Idea: {idea}
- All features use past data only. Walk-forward style: no tuning on the test period.
- Results looked strong across the whole sample, so we did not split it further.
- Parameters: {params}.
"""

LOG_MT_STRUCTURED = """# Research notes

- Idea: {idea}
- We searched a parameter grid (listed in params.json, {n} combinations) and kept the best by Sharpe after costs.
- Chosen: {params}. Annualised Sharpe after a $0.50 spread: {sharpe}.
"""

LOG_MT_PROSE = """# Research notes

- Idea: {idea}
- Over a couple of weeks I tried roughly {n} parameter combinations ({dims}) on the full history and kept the one
  with the best Sharpe after a $0.50 spread.
- Chosen: {params}. Annualised Sharpe after a $0.50 spread: {sharpe}.
"""

LOG_COST = """# Research notes

- Idea: {idea}
- Gross of costs the signal is clearly positive on every subsample.
- Parameters: {params}.
"""

IDEAS = {
    "A": "fade bars that move far more than recent volatility",
    "A2": "large moves partially retrace; hold the counter-trade for a few bars",
    "B": "fade large bars with a volatility-sized stop and a 1:1 target",
    "C": "learn the size of post-shock reversals with a regression refitted on an expanding window",
    "D": "trend following with an EMA crossover",
    "E": "channel breakout with a fixed holding period",
    "F": "gold has recurring intraday seasonality; hold a position through the best window of UTC hours",
}


def idea(tpl: str) -> str:
    return IDEAS[tpl.rstrip("0123456789") if tpl not in IDEAS else tpl]


# ---------------------------------------------------------------------------------------------------
# case specs
# ---------------------------------------------------------------------------------------------------
def fade_params(rng, tpl: str) -> dict:
    """Round values, as a researcher choosing parameters before testing would pick them.

    (The first bench used values like k=3.27; the auditor rightly read those as the output of an
    undisclosed search when the notes said "not tuned". See evals/CORRECTIONS.md.)
    """
    if tpl.startswith("C"):
        return {
            "k": float(rng.choice([3.0, 3.25, 3.5])),
            "hold": int(rng.choice([4, 6, 8])),
            "span": int(rng.choice([80, 100, 120, 150])),
        }
    p = {"k": float(rng.choice([2.25, 2.5, 2.75])), "span": int(rng.choice([80, 100, 120, 150]))}
    if tpl == "B":
        p.update({"stop_mult": float(rng.choice([2.5, 3.0, 3.5])), "cooldown": int(rng.choice([4, 6, 8]))})
    else:
        p["hold"] = int(rng.choice([4, 6, 8]))
    return p


def trend_params(rng, tpl: str) -> dict:
    if tpl.startswith("D"):
        return {"fast": int(rng.choice([10, 20, 30])), "slow": int(rng.choice([60, 100, 150]))}
    return {"window": int(rng.choice([24, 48, 96])), "hold": int(rng.choice([12, 24, 48]))}


def specs(rng) -> list[dict]:
    out = []
    # 30 real edges, clean code
    for tpl, n, htf_n in (("A", 8, 3), ("A2", 8, 3), ("B", 7, 0), ("C", 7, 0)):
        for i in range(n):
            out.append({"group": "survives", "truth": "SURVIVES", "flaw": "none", "tpl": tpl, "htf": i < htf_n,
                        "edge": round(float(rng.uniform(0.8, 1.3)), 2), "params": fade_params(rng, tpl), "log": "honest"})  # fmt: skip
    # 10 no edge, clean code
    for tpl, edge in (
        ("D", 0.0),
        ("D", 0.9),
        ("D", 0.0),
        ("E", 0.0),
        ("E", 0.9),
        ("E", 0.0),
        ("A", 0.0),
        ("A", 0.0),
        ("B", 0.0),
        ("B", 0.0),
    ):
        p = trend_params(rng, tpl) if tpl in ("D", "E") else fade_params(rng, tpl)
        out.append(
            {
                "group": "no_edge",
                "truth": "REJECT",
                "flaw": "no_edge",
                "tpl": tpl,
                "htf": False,
                "edge": edge,
                "params": p,
                "log": "honest",
            }
        )
    # 35 leaks: 7 classes x 5 templates; 3 on null markets, 2 on markets with a real edge
    for flaw, by_tpl in LEAKS.items():
        for j, (tpl, ov) in enumerate(by_tpl.items()):
            edge = 0.0 if j < 3 else round(float(rng.uniform(0.8, 1.2)), 2)
            p = trend_params(rng, tpl) if tpl.startswith(("D", "E")) else fade_params(rng, tpl)
            out.append({"group": "leak", "truth": "REJECT", "flaw": flaw, "tpl": tpl, "htf": False, "edge": edge,
                        "params": p, "override": ov, "log": "leak" if j % 2 == 0 else "none"})  # fmt: skip
    # 10 multiple testing on null markets: 5 logged in params.json, 5 only in prose
    for i in range(10):
        tpl = "D" if i % 2 == 0 else "F"
        out.append({"group": "multiple_testing", "truth": "REJECT", "flaw": "multiple_testing", "tpl": tpl, "htf": False,
                    "edge": 0.0, "log": "mt_structured" if i < 5 else "mt_prose"})  # fmt: skip
    # 5 real but small edges killed by costs
    for tpl in ("A", "A", "A2", "B", "B"):
        out.append({"group": "costs", "truth": "REJECT", "flaw": "costs", "tpl": tpl, "htf": False,
                    "edge": round(float(rng.uniform(0.15, 0.25)), 2), "params": fade_params(rng, tpl), "log": "cost"})  # fmt: skip
    return out


def grid_for(tpl: str, n_target: int) -> list[dict]:
    if tpl == "D":
        g = [{"fast": f, "slow": s} for f in range(20, 620, 20) for s in range(200, 5200, 200) if s > 2 * f]
    else:
        g = [
            {"start": a, "end": b, "side": sd}
            for a in range(22)
            for b in range(a + 1, 22)
            if b - a <= 8
            for sd in (1, -1)
        ]
    rng = np.random.default_rng(len(g) + n_target)
    idx = sorted(rng.choice(len(g), size=min(n_target, len(g)), replace=False))
    return [g[i] for i in idx]


# ---------------------------------------------------------------------------------------------------
# build + oracle
# ---------------------------------------------------------------------------------------------------
def write_case(d: Path, code: str, params: dict, log: str | None, extra: dict | None = None) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "strategy.py").write_text(code)
    (d / "params.json").write_text(json.dumps({"params": params, **(extra or {})}, indent=2) + "\n")
    if log:
        (d / "research_log.md").write_text(log)


def confirm(spec: dict, d: Path, bars) -> tuple[bool, dict]:
    s = load_strategy(d)
    g = spec["group"]
    if g == "survives":
        res = {
            c: checks.ALL[c](bars, s).result
            for c in ("future_blind", "backtest", "costs", "random_entry", "stability")
        }
        return all(v == "PASS" for v in res.values()), res
    if g == "no_edge":
        r = checks.backtest(bars, s).result
        return r == "REJECT", {"backtest": r}
    if g == "costs":
        c = checks.costs(bars, s)
        return c.result == "REJECT" and c.evidence["gross_mean"] > 0, {
            "costs": c.result,
            "gross": c.evidence["gross_mean"],
        }
    if g == "leak":
        return True, {"future_blind": checks.future_blind(bars, s).result}
    return True, {}


def build() -> list[dict]:
    rng = np.random.default_rng(SEED)
    if CASES.exists():
        shutil.rmtree(CASES)
    all_specs = specs(rng)
    order = rng.permutation(len(all_specs))  # case ids carry no information about the group
    manifest = []
    for case_no, k in enumerate(order, start=1):
        spec = all_specs[k]
        cid = f"case_{case_no:02d}"
        d = CASES / cid
        mseed = int(rng.integers(1, 10**6))
        for attempt in range(25):  # noqa: B007 (reported in the manifest)
            bars = market(n_days=N_DAYS, seed=mseed, edge=spec["edge"])
            extra, log = {}, None
            if spec["group"] == "multiple_testing":
                n = int(rng.integers(150, 281))
                grid = grid_for(spec["tpl"], n)
                code, _ = render(spec["tpl"])
                write_case(d, code, grid[0], None)
                strat = load_strategy(d)
                scores = []
                for p in grid:
                    t = checks.Strategy("positions", strat.fn, p).run(bars, 0.5)
                    all_days = pd.unique(bars["trading_day"])
                    daily = (
                        t.groupby("trading_day")["net_usd"].sum().reindex(all_days, fill_value=0.0)
                        if not t.empty
                        else None
                    )
                    scores.append(
                        -np.inf if daily is None or daily.std() == 0 else float(daily.mean() / daily.std())
                    )
                params = grid[int(np.argmax(scores))]
                sharpe_ann = round(float(np.max(scores)) * np.sqrt(252), 2)
                dims = "fast/slow EMA spans" if spec["tpl"] == "D" else "start hour, end hour and direction"
                if spec["log"] == "mt_structured":
                    extra = {"grid": grid, "n_trials": len(grid)}
                    log = LOG_MT_STRUCTURED.format(
                        idea=idea(spec["tpl"]), n=len(grid), params=params, sharpe=sharpe_ann
                    )
                else:
                    log = LOG_MT_PROSE.format(
                        idea=idea(spec["tpl"]),
                        n=round(len(grid), -1),
                        dims=dims,
                        params=params,
                        sharpe=sharpe_ann,
                    )
                write_case(d, code, params, log, extra)
                st = load_strategy(d)
                bt = checks.backtest(bars, st).result
                mt = checks.multiple_test(bars, st, n_trials=len(grid), grid=grid)
                # attractive alone (annualised Sharpe >= 0.6 after costs) yet fails deflation
                ok = sharpe_ann >= 0.6 and mt.result == "REJECT"
                evidence = {
                    "best_of": len(grid),
                    "sharpe_ann": sharpe_ann,
                    "backtest": bt,
                    "dsr": mt.evidence.get("dsr"),
                    "pbo": mt.evidence.get("pbo"),
                }
            else:
                code, line = render(spec["tpl"], spec.get("override"), spec["htf"])
                params = spec["params"]
                fmt = {"idea": idea(spec["tpl"]), "params": params, "n_days": N_DAYS}
                log = {"honest": LOG_HONEST, "leak": LOG_LEAK, "cost": LOG_COST}.get(spec["log"], "")
                write_case(d, code, params, log.format(**fmt) if log else None)
                ok, evidence = confirm(spec, d, bars)
            if ok:
                break
            mseed = int(rng.integers(1, 10**6))
        else:
            raise RuntimeError(f"{cid} ({spec['group']}/{spec['tpl']}) never confirmed")
        entry = {
            "id": cid,
            "group": spec["group"],
            "truth": spec["truth"],
            "flaw": spec["flaw"],
            # an overfit search on a null market is equally well rejected as "no real edge"
            "accept_flaws": ["multiple_testing", "no_edge"]
            if spec["flaw"] == "multiple_testing"
            else [spec["flaw"]],
            "template": spec["tpl"],
            "kind": KIND[spec["tpl"]],
            "file": "strategy.py" if spec["group"] == "leak" else None,
            "line": line if spec["group"] == "leak" else None,
            "market": {"n_days": N_DAYS, "seed": mseed, "edge": spec["edge"]},
            "oracle": evidence,
            "attempts": attempt + 1,
        }
        manifest.append(entry)
        print(f"{cid} {spec['group']:16s} {spec['flaw']:24s} {spec['tpl']:3s} {evidence}", flush=True)
    MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n")
    return manifest


if __name__ == "__main__":
    build()
