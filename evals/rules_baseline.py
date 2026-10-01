"""Rules-only baseline: run every check with fixed thresholds; reject if any check rejects. No LLM.

    python -m evals.rules_baseline         # writes runs/evals/rules/results.jsonl and caches check outputs

The check outputs are cached per case in runs/checks/<case>.json so agent runs reuse them (same numbers,
less compute). The cache holds check results only, never the manifest.
"""

from __future__ import annotations

import json
import time

from evals.scoring import score
from skeptic import checks, config
from skeptic.cases import load_strategy, read_params
from skeptic.synth import market

ROOT = config.ROOT
MANIFEST = ROOT / "bench" / "manifest.json"
CASES = ROOT / "bench" / "cases"
CACHE = config.RUNS_DIR / "checks"
OUT = config.RUNS_DIR / "evals" / "rules"
ORDER = [("future_blind", "leak"), ("multiple_test", "multiple_testing"), ("costs", "costs"),
         ("backtest", "no_edge"), ("random_entry", "no_edge"), ("stability", "no_edge")]  # fmt: skip


def run_checks(case_id: str, market_spec: dict) -> dict:
    """All checks with default arguments for one case (cached)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{case_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    bars = market(**market_spec)
    d = CASES / case_id
    s = load_strategy(d)
    meta = read_params(d)
    out = {}
    for name in ("future_blind", "backtest", "costs", "random_entry", "stability", "sessions"):
        t0 = time.perf_counter()
        out[name] = checks.ALL[name](bars, s).to_dict() | {"seconds": round(time.perf_counter() - t0, 2)}
    out["multiple_test"] = checks.multiple_test(
        bars, s, n_trials=meta.get("n_trials"), grid=meta.get("grid")
    ).to_dict()
    path.write_text(json.dumps(out, default=str))
    return out


def verdict_from(results: dict) -> dict:
    for name, flaw in ORDER:
        if results[name]["result"] == "REJECT":
            return {"verdict": "REJECT", "flaw_class": flaw, "file": None, "line": None, "because": name}
    return {"verdict": "SURVIVES", "flaw_class": "none", "file": None, "line": None, "because": None}


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in manifest:
        res = run_checks(case["id"], case["market"])
        v = verdict_from(res)
        rows.append({"id": case["id"], "verdict": v, "score": score(case, v)})
        print(
            case["id"], case["group"], v["verdict"], v["because"], rows[-1]["score"]["verdict_ok"], flush=True
        )
    (OUT / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


if __name__ == "__main__":
    main()
