"""The audit loop and its tools, with a scripted fake model (no API calls, no cost)."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from skeptic.agent.loop import Auditor
from skeptic.agent.tools import CaseTools


def usage():
    return NS(input_tokens=1000, output_tokens=100, cache_creation_input_tokens=0, cache_read_input_tokens=0)


def tool_use(name, inp, i):
    return NS(type="tool_use", name=name, input=inp, id=f"tu_{i}")


def resp(blocks):
    return NS(content=blocks, stop_reason="tool_use", usage=usage())


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.messages = self

    def create(self, **kw):
        self.requests.append(kw)
        step = self.script.pop(0)
        return step(kw) if callable(step) else step


@pytest.fixture
def case(tmp_path):
    d = tmp_path / "case_01"
    d.mkdir()
    (d / "strategy.py").write_text("def positions(bars, params):\n    return bars['close'].shift(-1)\n")
    (d / "research_log.md").write_text("# notes\n")
    (tmp_path / "manifest.json").write_text('{"secret": "ground truth"}')
    return d


def checks_stub(name, n_trials):
    return {"name": name, "result": "PASS", "evidence": {"n_trials": n_trials}, "caveats": ["stub"]}


def test_tools_are_confined_to_the_case_folder(case):
    t = CaseTools(case, checks_stub)
    assert "error" in t.call("read_file", {"path": "../manifest.json"})
    assert "error" in t.call("read_file", {"path": "/etc/passwd"})
    assert [f["path"] for f in t.call("list_files", {})["files"]] == ["research_log.md", "strategy.py"]
    out = t.call("read_file", {"path": "strategy.py"})
    assert "   2|     return bars['close'].shift(-1)" in out["content"]


def test_undeclared_arguments_and_tools_are_refused(case):
    t = CaseTools(case, checks_stub, allowed=["run_check", "submit_verdict"])
    assert "error" in t.call("read_file", {"path": "strategy.py"})  # not allowed in this ablation
    assert "error" in t.call("run_check", {"name": "backtest", "spread_usd": 0.0})  # can't set its own costs
    assert [s["name"] for s in t.specs()] == ["run_check", "submit_verdict"]


def test_audit_records_the_verdict(case):
    client = FakeClient([
        resp([tool_use("read_file", {"path": "strategy.py"}, 1)]),
        resp([tool_use("submit_verdict", {"verdict": "REJECT", "flaw_class": "lookahead_shift", "file": "strategy.py",
                                          "line": 2, "summary": "shift(-1) at strategy.py:2"}, 2)]),
    ])  # fmt: skip
    a = Auditor(model="claude-sonnet-5", client=client).audit("case_01", CaseTools(case, checks_stub))
    assert a.verdict["verdict"] == "REJECT" and a.verdict["line"] == 2 and not a.forced_finish
    assert [s["tool"] for s in a.steps] == ["read_file", "submit_verdict"]
    assert a.cost_usd > 0


def test_tool_cap_forces_a_verdict(case):
    def loop_or_finish(kw):
        if kw.get("tool_choice") == {"type": "tool", "name": "submit_verdict"}:
            return resp(
                [
                    tool_use(
                        "submit_verdict", {"verdict": "REJECT", "flaw_class": "no_edge", "summary": "cap"}, 99
                    )
                ]
            )
        return resp([tool_use("run_check", {"name": "backtest"}, len(kw["messages"]))])

    client = FakeClient([loop_or_finish] * 10)
    a = Auditor(model="claude-sonnet-5", client=client, max_tool_calls=3).audit(
        "c", CaseTools(case, checks_stub)
    )
    assert a.forced_finish and "tool_calls" in a.limits_hit and a.verdict["summary"] == "cap"
    assert sum(1 for s in a.steps if s["tool"] == "run_check") == 3
    assert "output_config" not in client.requests[-1]  # forced tool use is sent without thinking


def test_model_without_tool_use_is_pushed_to_verdict(case):
    client = FakeClient([
        resp([NS(type="text", text="I think it's fine.")]),
        resp([tool_use("submit_verdict", {"verdict": "SURVIVES", "flaw_class": "none", "summary": "ok"}, 1)]),
    ])  # fmt: skip
    a = Auditor(model="claude-sonnet-5", client=client).audit("c", CaseTools(case, checks_stub))
    assert a.verdict["verdict"] == "SURVIVES" and "no_verdict" in a.limits_hit
