"""Command line: audit your own strategy folder.

    skeptic describe <folder>                       what would be audited (files, contract, data, spread)
    skeptic check <folder> <check> [--n-trials N]    one deterministic check, no API call
    skeptic audit <folder> [--model M]               the auditor measured on the bench (needs ANTHROPIC_API_KEY)

Exit codes: 0 = SURVIVES CHECKS, or a check that did not reject (PASS or INFO); 1 = REJECT; 2 = any error,
including an exception raised by the strategy itself. Gate CI on `skeptic audit`, not on single checks:
`multiple_test` without a trial count returns INFO (exit 0), which is a caveat, not a pass.
`skeptic audit` uses the same prompt, tools and caps as the bench's `sonnet_full` configuration; only the
data source differs (your folder's declared data instead of a bench market).
"""

from __future__ import annotations

import argparse
import json
import sys

from skeptic import config
from skeptic.agent.loop import Auditor
from skeptic.agent.tools import CaseTools
from skeptic.folder import CHECKS, FolderError, open_folder


def _print(obj: dict) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_describe(a: argparse.Namespace) -> int:
    _print(open_folder(a.folder).describe())
    return 0


def cmd_check(a: argparse.Namespace) -> int:
    r = open_folder(a.folder).run(a.check, a.n_trials)
    _print(r)
    return 1 if r["result"] == "REJECT" else 0


def cmd_audit(a: argparse.Namespace) -> int:
    folder = open_folder(a.folder)
    folder.describe()  # fail fast on a bad folder, before any API spend
    tools = CaseTools(folder.root, lambda name, n: folder.run(name, n))
    aud = Auditor(model=a.model, max_cost_usd=a.max_cost, config_name="cli")
    res = aud.audit(folder.root.name, tools, trace_dir=config.RUNS_DIR / "audits")
    if res.error or not res.verdict:
        print(f"audit failed: {res.error or 'no verdict'}", file=sys.stderr)
        return 2
    v = res.verdict
    word = "SURVIVES CHECKS" if v["verdict"] == "SURVIVES" else "REJECT"
    where = f"  ({v['file']}:{v['line']})" if v.get("file") and v.get("line") else ""
    print(f"\n{word}  [{v.get('flaw_class')}]{where}\n\n{v.get('summary', '')}\n")
    for e in v.get("evidence") or []:
        print(f"  - {e}")
    print(f"\n{len(res.steps)} tool calls, ${res.cost_usd:.3f}, {res.latency_s:.0f}s, model {res.model}")
    if v["verdict"] == "SURVIVES":
        print("SURVIVES CHECKS means these checks found nothing. It does not mean the strategy makes money.")
    return 0 if v["verdict"] == "SURVIVES" else 1


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="skeptic", description="Try to kill a trading strategy.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("describe", help="show what would be audited")
    d.add_argument("folder")
    d.set_defaults(fn=cmd_describe)
    c = sub.add_parser("check", help="run one deterministic check")
    c.add_argument("folder")
    c.add_argument("check", choices=CHECKS)
    c.add_argument("--n-trials", type=int, help="multiple_test: configurations tried")
    c.set_defaults(fn=cmd_check)
    au = sub.add_parser("audit", help="run the LLM auditor (Anthropic API)")
    au.add_argument("folder")
    au.add_argument("--model", default=config.MODEL)
    au.add_argument("--max-cost", type=float, default=0.40, help="USD cap for this audit")
    au.set_defaults(fn=cmd_audit)
    a = ap.parse_args(argv)
    try:
        code = a.fn(a)
    except FolderError as e:
        print(f"skeptic: {e}", file=sys.stderr)
        code = 2
    except Exception as e:  # a crash must never look like a verdict (exit 1 means REJECT)
        print(f"skeptic: {type(e).__name__}: {e}", file=sys.stderr)
        code = 2
    sys.exit(code)


if __name__ == "__main__":
    main()
