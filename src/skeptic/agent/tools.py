"""The agent's tools, bound to one case. Read-only: the agent can read the case folder and run checks.

Nothing here can write a file, edit a strategy, search parameters, or reach the bench manifest. File
access is confined to the case folder (paths are resolved and must stay inside it).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

FLAW_CLASSES = [
    "none", "no_edge", "costs", "multiple_testing",
    "lookahead_shift", "centered_window", "fullsample_stat", "htf_resample",
    "fit_on_full_sample", "selection_on_full_sample", "unpurged_labels",
    "process",  # a research write-up breaks its own rules (gates, out-of-sample discipline, trial counts)
]  # fmt: skip
CHECKS = ["future_blind", "backtest", "costs", "random_entry", "multiple_test", "stability", "sessions"]
MAX_LINES = 400
MAX_FILE_BYTES = 200_000


def _schema(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


SPECS = {
    "list_files": {
        "description": "List the files in the case folder (strategy code, params, research notes) with their sizes.",
        "input_schema": _schema({}),
    },
    "read_file": {
        "description": (
            "Read a text file from the case folder with line numbers (cite these as file:line). "
            f"At most {MAX_LINES} lines per call; use start_line to page."
        ),
        "input_schema": _schema(
            {
                "path": {"type": "string", "description": "Relative path inside the case folder."},
                "start_line": {"type": "integer", "minimum": 1},
            },
            ["path"],
        ),
    },
    "run_check": {
        "description": (
            "Run one deterministic check on the strategy and its market data. Every number you report must "
            "come from these results. Checks: future_blind (truncation test for look-ahead), backtest (net "
            "expectancy with a day-clustered CI at a $0.50 spread), costs (break-even spread), random_entry "
            "(same exits, random entries), multiple_test (deflated Sharpe; needs n_trials, which you must "
            "find in the notes or params), stability (time folds), sessions (where the PnL comes from)."
        ),
        "input_schema": _schema(
            {
                "name": {"type": "string", "enum": CHECKS},
                "n_trials": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "multiple_test only: configurations tried.",
                },
            },
            ["name"],
        ),
    },
    "submit_verdict": {
        "description": (
            "Finish the audit. REJECT if any check rejects, or if the code or notes contain a flaw (even when "
            "the checks pass). SURVIVES only if every relevant check passes and you found no flaw. Name the "
            "single most important flaw class, and for a code flaw the file and line where it is."
        ),
        "input_schema": _schema(
            {
                "verdict": {"type": "string", "enum": ["REJECT", "SURVIVES"]},
                "flaw_class": {"type": "string", "enum": FLAW_CLASSES},
                "file": {"type": ["string", "null"]},
                "line": {"type": ["integer", "null"]},
                "summary": {
                    "type": "string",
                    "description": "Two to five sentences, citing check results and file:line.",
                },
                "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            },
            ["verdict", "flaw_class", "summary"],
        ),
    },
}


class CaseTools:
    """Tool implementations for one case.

    `check_runner(name, n_trials)` returns a check result dict; the eval wires it to cached results.
    `allowed` restricts which tools exist (for the ablations).
    """

    def __init__(
        self,
        case_dir: Path,
        check_runner: Callable[[str, int | None], dict],
        allowed: list[str] | None = None,
    ):
        self.root = Path(case_dir).resolve()
        self.check_runner = check_runner
        self.allowed = allowed or list(SPECS)
        self.verdict: dict | None = None

    def specs(self) -> list[dict]:
        return [{"name": n, **SPECS[n]} for n in self.allowed]

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name not in self.allowed:
            return {"error": f"unknown tool {name!r}"}
        props = SPECS[name]["input_schema"]["properties"]
        extra = set(args) - set(props)
        if extra:
            return {"error": f"unknown argument(s) {sorted(extra)}"}
        try:
            return getattr(self, f"_{name}")(**args)
        except Exception as e:  # tool errors go back to the model as recoverable errors
            return {"error": f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"}

    def _resolve(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise PermissionError("path is outside the case folder")
        if p.is_symlink() or not p.is_file():
            raise FileNotFoundError(rel)
        return p

    def _list_files(self) -> dict:
        files = sorted(p for p in self.root.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        return {"files": [{"path": str(p.relative_to(self.root)), "bytes": p.stat().st_size} for p in files]}

    def _read_file(self, path: str, start_line: int = 1) -> dict:
        p = self._resolve(path)
        if p.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("file too large")
        lines = p.read_text(errors="replace").splitlines()
        chunk = lines[start_line - 1 : start_line - 1 + MAX_LINES]
        body = "\n".join(f"{start_line + i:4d}| {line}" for i, line in enumerate(chunk))
        more = start_line - 1 + MAX_LINES < len(lines)
        return {
            "path": path,
            "lines": len(lines),
            "content": body,
            **({"next_start_line": start_line + MAX_LINES} if more else {}),
        }

    def _run_check(self, name: str, n_trials: int | None = None) -> dict:
        return self.check_runner(name, n_trials)

    def _submit_verdict(self, **v) -> dict:
        self.verdict = v
        return {"ok": True}


def compact(result: dict) -> str:
    """Tool result text for the model: caveats first, so truncation never drops them."""
    ordered = {k: result[k] for k in ("error", "result", "caveats", "evidence") if k in result}
    ordered |= {k: v for k, v in result.items() if k not in ordered and k != "seconds"}
    return json.dumps(ordered, default=str)
