"""Phase 7 acceptance: the shipped path (Claude Code + /skeptic skill + skeptic-mcp) on a bench subset.

    python -m evals.p7_claude_code            # needs ANTHROPIC_API_KEY and the `claude` CLI; ~$2

The subset is fixed before running: 20 cases drawn with seed 7, stratified by group (6 real edges, 8 leaks
of which 4 the truncation probe can't see, 2 multiple testing, 2 costs, 2 no edge). It is not chosen by
where the API auditor failed.

Each case becomes an ordinary user folder, the way a stranger would use Skeptic: the case's own files,
plus the market written to `bars.parquet` and a `data` entry in params.json pointing at it. The market's
seed and planted edge are not written anywhere the model can read. Each case runs in a fresh headless
session:
- MCP servers: only this repo's `.mcp.json` (`--strict-mcp-config`).
- Built-in tools: only `Skill`. No Bash, Read or Write, so the model reads files and gets numbers only
  through skeptic-mcp, and cannot reach the manifest.
- The prompt is `/skeptic <folder>`; the skill fixes the output format, which is parsed here and scored by
  the bench's deterministic scorer. The API auditor's verdicts on the same 20 cases are shown alongside.

Separately, the API auditor's wrong verdicts on the full bench are rerun through the same path, in their
own section. Those cases are chosen *because* they failed, so they are reported case by case, never as a
rate. Writes docs/results/claude_code_skill_p7.md.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

from evals.rules_baseline import CASES, MANIFEST
from evals.scoring import FLAW_CLASSES, score
from skeptic import config
from skeptic.folder import StrategyFolder
from skeptic.synth import market

OUT = config.ROOT / "docs" / "results" / "claude_code_skill_p7.md"
RUN_DIR = config.RUNS_DIR / "p7"
STAGE = RUN_DIR / "cases"
MODEL = os.environ.get("SKEPTIC_MODEL", config.MODEL)
TOOLS = [f"mcp__skeptic__{n}" for n in ("describe_folder", "read_file", "run_check")]
QUOTA = {"survives": 6, "multiple_testing": 2, "costs": 2, "no_edge": 2}
SEED = 7


def pick(manifest: list[dict]) -> list[dict]:
    rng = np.random.default_rng(SEED)
    out = []
    for g, n in QUOTA.items():
        pool = [c for c in manifest if c["group"] == g]
        out += [pool[i] for i in sorted(rng.choice(len(pool), n, replace=False))]
    leaks = [c for c in manifest if c["group"] == "leak"]
    for blind in (True, False):  # 4 the probe misses, 4 it catches
        pool = [c for c in leaks if (c["oracle"].get("future_blind") == "PASS") == blind]
        out += [pool[i] for i in sorted(rng.choice(len(pool), 4, replace=False))]
    return sorted(out, key=lambda c: c["id"])


def stage(case: dict) -> str:
    """Copy a bench case into a plain user folder with its market as a data file. Returns the path."""
    d = STAGE / case["id"]
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    for f in ("strategy.py", "research_log.md", "params.json"):
        if (CASES / case["id"] / f).exists():
            shutil.copy(CASES / case["id"] / f, d / f)
    market(**case["market"]).rename_axis("ts").to_parquet(d / "bars.parquet")
    meta = json.loads((d / "params.json").read_text()) if (d / "params.json").exists() else {}
    meta |= {"data": {"source": "file", "path": "bars.parquet"}, "spread_usd": config.REALISTIC_SPREAD_USD}
    (d / "params.json").write_text(json.dumps(meta, indent=2) + "\n")
    return str(d.relative_to(config.ROOT))


def parity(case: dict, folder: str) -> bool:
    """The staged folder must give the same check numbers the bench agents saw (runs/checks cache)."""
    cached = json.loads((config.RUNS_DIR / "checks" / f"{case['id']}.json").read_text())
    f = StrategyFolder(config.ROOT / folder)
    return all(
        json.loads(json.dumps(f.run(n)["evidence"], default=str)) == cached[n]["evidence"]
        for n in ("backtest", "future_blind")
    )


def claude_cmd(prompt: str) -> list[str]:
    return [
        "claude", "-p", prompt,
        "--model", MODEL,
        "--setting-sources", "project",
        "--mcp-config", str(config.ROOT / ".mcp.json"), "--strict-mcp-config",
        "--tools", "Skill",
        "--allowedTools", ",".join(TOOLS),
        "--no-chrome", "--no-session-persistence",
        "--max-budget-usd", "0.60",
        "--output-format", "stream-json", "--verbose",
    ]  # fmt: skip


def parse(answer: str) -> dict[str, Any]:
    v = re.search(r"Verdict:\s*\**\s*(REJECT|SURVIVES)", answer, re.I)
    fc = re.search(r"Flaw class:\s*`?([a-z_]+)`?", answer, re.I)
    loc = re.search(r"Location:\s*`?([\w./-]+\.\w+):(\d+)", answer)
    flaw = fc.group(1).lower() if fc else "none"
    return {
        "verdict": v.group(1).upper() if v else "",
        "flaw_class": flaw if flaw in FLAW_CLASSES or flaw == "process" else "none",
        "file": loc.group(1) if loc else None,
        "line": int(loc.group(2)) if loc else None,
    }


def run_one(case: dict, folder: str) -> dict[str, Any]:
    t0 = time.monotonic()
    proc = subprocess.run(claude_cmd(f"/skeptic {folder}"), cwd=config.ROOT, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=900)  # fmt: skip
    (RUN_DIR / f"{case['id']}.jsonl").write_text(proc.stdout)
    events = [json.loads(x) for x in proc.stdout.splitlines() if x.startswith("{")]
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
    final = next((e for e in reversed(events) if e.get("type") == "result"), {})
    calls, texts = [], []
    for e in events:
        if e.get("type") == "assistant":
            for c in e["message"]["content"]:
                if c["type"] == "tool_use":
                    calls.append({"name": c["name"], "input": c["input"]})
                elif c["type"] == "text":
                    texts.append(c["text"])
    answer = final.get("result") or (texts[-1] if texts else "")
    v = parse(answer)
    return {
        "id": case["id"], "group": case["group"], "truth": case["truth"], "flaw": case["flaw"],
        "verdict": v, "score": score(case, v), "answer": answer, "tool_calls": calls,
        "tools_available": init.get("tools", []), "skill_loaded": "skeptic" in (init.get("skills") or []),
        "mcp_status": {s["name"]: s["status"] for s in init.get("mcp_servers", [])},
        "cost_usd": float(final.get("total_cost_usd") or 0), "latency_s": round(time.monotonic() - t0, 1),
        "exit_code": proc.returncode, "stderr_tail": proc.stderr.strip().splitlines()[-3:],
    }  # fmt: skip


def render(rows: list[dict], api: dict[str, dict], parity_ok: dict[str, bool], version: str,
           targeted: list[dict]) -> str:  # fmt: skip
    n = len(rows)
    ok = sum(r["score"]["verdict_ok"] for r in rows)
    reason = sum(r["score"]["verdict_ok"] and r["score"]["coarse_ok"] for r in rows)
    leaks = [r for r in rows if r["group"] == "leak"]
    located = sum(bool(r["score"]["located"]) for r in leaks)
    api_ok = sum(api[r["id"]]["score"]["verdict_ok"] for r in rows)
    api_reason = sum(api[r["id"]]["score"]["verdict_ok"] and api[r["id"]]["score"]["coarse_ok"] for r in rows)
    api_loc = sum(bool(api[r["id"]]["score"]["located"]) for r in leaks)
    outside = sorted({c["name"] for r in rows for c in r["tool_calls"] if c["name"] not in (*TOOLS, "Skill")})
    cost = sum(r["cost_usd"] for r in rows)
    api_wrong = sorted(i for i, x in api.items() if not x["score"]["verdict_ok"])
    in_subset = [i for i in api_wrong if i in {r["id"] for r in rows}]
    L = [
        "# Phase 7: the shipped path, Claude Code + `/skeptic` + skeptic-mcp",
        "",
        "Generated by `python -m evals.p7_claude_code`. Do not edit by hand.",
        "",
        f"*Run {dt.date.today()} with {version}, model `{MODEL}`. 20 bench cases fixed in advance (seed {SEED}, "
        "stratified by group; see the script's docstring), each staged as an ordinary strategy folder with its "
        "market in `bars.parquet`, each in a fresh headless session: "
        '`claude -p "/skeptic <folder>" --mcp-config .mcp.json --strict-mcp-config --tools Skill ...`. '
        "Scored by the bench's deterministic scorer.*",
        "",
        "| | Claude Code + /skeptic | API auditor (bench run, same cases) |",
        "|---|---:|---:|",
        f"| Verdict correct | **{ok}/{n}** | {api_ok}/{n} |",
        f"| Correct for the right reason | **{reason}/{n}** | {api_reason}/{n} |",
        f"| Leak line found (±3) | **{located}/{len(leaks)}** | {api_loc}/{len(leaks)} |",
        f"| Cost | ${cost:.2f} (${cost / n:.3f}/case) | ${sum(api[r['id']]['cost_usd'] for r in rows):.2f} |",
        "",
        f"- Staged folders reproduce the bench's check numbers exactly: {sum(parity_ok.values())}/{n} "
        "(backtest and future_blind evidence compared with the cache the bench agents read).",
        f"- Skill loaded in {sum(r['skill_loaded'] for r in rows)}/{n} sessions; MCP server connected in "
        f"{sum(r['mcp_status'].get('skeptic') == 'connected' for r in rows)}/{n}. Tools called outside "
        f"skeptic-mcp: {', '.join(outside) if outside else 'none'}.",
        "- 20 cases is a smoke test of the shipped path, not a second benchmark: one wrong verdict moves the "
        "rate by 5 points.",
        f"- The API auditor's wrong verdicts on the full bench ({', '.join(api_wrong) or 'none'}) "
        + (
            f"include {', '.join(in_subset)} from this subset."
            if in_subset
            else "are not in this subset; they are rerun separately at the end, case by case."
        ),
        "- Claude Code costs more per case than the bench loop because its own system prompt and tool list ride "
        "along with every request.",
        "",
        "| Case | Group / planted flaw | Truth | Claude Code verdict | Class | Location | Right? | API auditor | Checks run | $ |",
        "|---|---|---|---|---|---|---|---|---|---:|",
    ]
    for r in rows:
        v, a = r["verdict"], api[r["id"]]
        checks = [c["input"].get("name") for c in r["tool_calls"] if c["name"].endswith("run_check")]
        loc = f"{v['file']}:{v['line']}" if v.get("line") else "—"
        right = "✅" if r["score"]["verdict_ok"] else "❌"
        if r["score"]["verdict_ok"] and not r["score"]["coarse_ok"]:
            right = "✅ (wrong reason)"
        L.append(
            f"| {r['id']} | {r['group']} / {r['flaw']} | {r['truth']} | {v['verdict'] or '(unparsed)'} | "
            f"{v['flaw_class']} | {loc} | {right} | {a['verdict'].get('verdict')} "
            f"{'✅' if a['score']['verdict_ok'] else '❌'} | {', '.join(checks)} | {r['cost_usd']:.3f} |"
        )
    if targeted:
        L += ["", "## The API auditor's errors, rerun through `/skeptic`",
              "Selected because the API auditor got them wrong, so this is case by case, not a rate.", "",
              "| Case | Truth | API auditor | Claude Code + /skeptic | Class given | $ |", "|---|---|---|---|---|---:|"]  # fmt: skip
        for r in targeted:
            a = api[r["id"]]["verdict"]
            L.append(f"| {r['id']} | {r['truth']} | {a.get('verdict')} ({a.get('flaw_class')}) | "
                     f"{r['verdict']['verdict'] or '(unparsed)'} {'✅' if r['score']['verdict_ok'] else '❌'} | "
                     f"{r['verdict']['flaw_class']} | {r['cost_usd']:.3f} |")  # fmt: skip
    wrong = [r for r in rows + targeted if not r["score"]["verdict_ok"]]
    if wrong:
        L += ["", "## Wrong verdicts, in full", ""]
        for r in wrong:
            L += [f"### {r['id']} ({r['group']} / {r['flaw']}, truth {r['truth']})", "",
                  *[f"> {x}" if x else ">" for x in r["answer"].strip().splitlines()], ""]  # fmt: skip
    return "\n".join(L) + "\n"


def main() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text())
    cases = pick(manifest)
    folders = {c["id"]: stage(c) for c in cases}
    parity_ok = {c["id"]: parity(c, folders[c["id"]]) for c in cases}
    print(f"staged {len(cases)} cases; parity {sum(parity_ok.values())}/{len(cases)}", flush=True)
    out = RUN_DIR / "results.jsonl"
    done = {json.loads(x)["id"]: json.loads(x) for x in out.read_text().splitlines()} if out.exists() else {}

    def one(c: dict) -> dict:
        if c["id"] in done:
            return done[c["id"]]
        r = run_one(c, folders[c["id"]])
        with out.open("a") as f:
            f.write(json.dumps(r, default=str) + "\n")
        print(f"{c['id']} {c['group']:16s} truth={c['truth']:8s} got={r['verdict']['verdict']:8s} "
              f"{r['verdict']['flaw_class']:24s} ok={r['score']['verdict_ok']} ${r['cost_usd']:.3f} "
              f"{r['latency_s']:.0f}s", flush=True)  # fmt: skip
        return r

    with ThreadPoolExecutor(max_workers=4) as ex:
        rows = list(ex.map(one, cases))
    api = {
        x["id"]: x
        for x in map(
            json.loads, (config.RUNS_DIR / "evals" / "sonnet_full" / "results.jsonl").read_text().splitlines()
        )
    }
    by_id = {c["id"]: c for c in manifest}
    extra = [by_id[i] for i in sorted(api) if not api[i]["score"]["verdict_ok"] and i not in folders]
    folders |= {c["id"]: stage(c) for c in extra}
    with ThreadPoolExecutor(max_workers=4) as ex:
        targeted = list(ex.map(one, extra))
    version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
    OUT.write_text(render(rows, api, parity_ok, version, targeted))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
