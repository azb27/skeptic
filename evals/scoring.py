"""Deterministic scoring of a verdict against the bench manifest. No LLM judge."""

from __future__ import annotations

LEAK_CLASSES = {
    "lookahead_shift", "centered_window", "fullsample_stat", "htf_resample",
    "fit_on_full_sample", "selection_on_full_sample", "unpurged_labels",
}  # fmt: skip
COARSE = {**{c: "leak" for c in LEAK_CLASSES}, "multiple_testing": "multiple_testing", "costs": "costs",
          "no_edge": "no_edge", "none": "none"}  # fmt: skip
FLAW_CLASSES = sorted(COARSE)
LINE_TOLERANCE = 3


def coarse(flaw: str | None) -> str:
    return COARSE.get(flaw or "none", "unknown")


def score(case: dict, verdict: dict) -> dict:
    """`verdict` = {"verdict": REJECT|SURVIVES, "flaw_class": str, "file": str|None, "line": int|None}."""
    v = (verdict.get("verdict") or "").upper()
    flaw = verdict.get("flaw_class") or "none"
    accept = case.get("accept_flaws") or [case["flaw"]]
    out = {
        "verdict_ok": v == case["truth"],
        "coarse_ok": coarse(flaw) in {coarse(a) for a in accept},
        "fine_ok": flaw in accept,
        "located": None,
    }
    if case["group"] == "leak":
        line = verdict.get("line")
        out["located"] = bool(
            line is not None and (verdict.get("file") or "strategy.py").endswith(case["file"])
            and abs(int(line) - case["line"]) <= LINE_TOLERANCE
        )  # fmt: skip
    return out
