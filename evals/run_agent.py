"""Run the auditor over the bench in one configuration. Resumable; each case gets a fresh Auditor.

    python -m evals.run_agent --config sonnet_full [--ids case_01,case_02] [--limit N] [--budget 5] [--workers 4]

Check results come from the same cache as the rules-only baseline, so every configuration sees identical
numbers. The manifest is read here (to score), never passed to the agent.
"""

from __future__ import annotations

import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from evals.rules_baseline import CASES, MANIFEST, run_checks
from evals.scoring import score
from skeptic import checks, config
from skeptic.agent.loop import Auditor
from skeptic.agent.tools import CaseTools
from skeptic.cases import load_strategy, read_params
from skeptic.synth import market

CONFIGS = {
    "sonnet_full": {"model": config.MODEL, "allowed": None, "note": ""},
    "haiku_full": {"model": config.CHEAP_MODEL, "allowed": None, "note": ""},
    "sonnet_nocode": {
        "model": config.MODEL,
        "allowed": ["run_check", "submit_verdict"],
        "note": "In this configuration you cannot read files. Decide from the checks alone; give no file or line.",
    },
    "sonnet_nochecks": {
        "model": config.MODEL,
        "allowed": ["list_files", "read_file", "submit_verdict"],
        "note": "In this configuration no checks are available. Decide from the code and notes alone, and quote no numbers.",
    },
}
_lock = threading.Lock()


def check_runner(case: dict):
    cached = run_checks(case["id"], case["market"])
    extra: dict[int, dict] = {}

    def run(name: str, n_trials: int | None) -> dict:
        if name != "multiple_test" or n_trials is None:
            r = dict(cached[name])
            if name == "multiple_test" and r["result"] == "INFO":
                r["caveats"] = [*r["caveats"], "Pass n_trials to run the deflation."]
            return r
        meta = read_params(CASES / case["id"])
        if n_trials == meta.get("n_trials"):
            return cached["multiple_test"]
        if n_trials not in extra:
            bars = market(**case["market"])
            extra[n_trials] = checks.multiple_test(
                bars, load_strategy(CASES / case["id"]), n_trials=n_trials
            ).to_dict()
        return extra[n_trials]

    return run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, choices=sorted(CONFIGS))
    ap.add_argument("--ids")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--budget", type=float, default=5.0, help="stop starting new cases past this many USD")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    cfg = CONFIGS[a.config]
    manifest = json.loads(MANIFEST.read_text())
    if a.ids:
        want = set(a.ids.split(","))
        manifest = [c for c in manifest if c["id"] in want]
    if a.limit:
        manifest = manifest[: a.limit]
    out_dir = config.RUNS_DIR / "evals" / a.config
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "results.jsonl"
    done = {json.loads(line)["id"] for line in out.read_text().splitlines()} if out.exists() else set()
    spent = (
        sum(json.loads(line)["cost_usd"] for line in out.read_text().splitlines()) if out.exists() else 0.0
    )
    todo = [c for c in manifest if c["id"] not in done]
    print(f"{a.config}: {len(todo)} to run, ${spent:.2f} spent so far", flush=True)

    def one(case: dict) -> None:
        nonlocal spent
        with _lock:
            if spent >= a.budget:
                return
        tools = CaseTools(CASES / case["id"], check_runner(case), allowed=cfg["allowed"])
        aud = Auditor(model=cfg["model"], config_name=a.config, task_note=cfg["note"])
        res = aud.audit(case["id"], tools, trace_dir=out_dir / "traces")
        v = res.verdict or {"verdict": "", "flaw_class": "none"}
        row = {"id": case["id"], "group": case["group"], "truth": case["truth"], "flaw": case["flaw"],
               "verdict": v, "score": score(case, v), **{k: v for k, v in asdict(res).items() if k in
               ("cost_usd", "latency_s", "limits_hit", "forced_finish", "error", "usage")},
               "tool_calls": len(res.steps)}  # fmt: skip
        with _lock:
            spent += res.cost_usd
            with out.open("a") as f:
                f.write(json.dumps(row, default=str) + "\n")
        s = row["score"]
        print(f"{case['id']} {case['group']:16s} truth={case['truth']:8s} got={v.get('verdict', ''):8s} "
              f"{v.get('flaw_class', ''):24s} ok={s['verdict_ok']} loc={s['located']} ${res.cost_usd:.3f} "
              f"{res.latency_s:.0f}s {res.error or ''}", flush=True)  # fmt: skip

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(one, todo))
    print(f"done; ${spent:.2f} total", flush=True)


if __name__ == "__main__":
    main()
