"""The audit loop: plain Anthropic Messages API, one audit per Auditor (port of Stockroom's agent loop).

Guarantees (tests/test_agent.py, with a scripted fake model):
* at most `max_tool_calls` tool calls; then the model is forced to call submit_verdict
* a cost cap per audit and a wall-clock limit, with the same forced finish
* tools are only the CaseTools bound to one case folder (read-only), so the manifest is unreachable
* every audit is traced to runs/traces/*.jsonl
"""

from __future__ import annotations

import datetime as dt
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

import anthropic

from skeptic import config
from skeptic.agent.pricing import EFFORT_MODELS, Usage, check_model, cost_usd
from skeptic.agent.prompts import SYSTEM, TASK
from skeptic.agent.tools import CaseTools, compact

MAX_RESULT_CHARS = 20_000


@dataclass
class Audit:
    case: str
    model: str
    config: str
    started_at: str
    verdict: dict | None = None
    steps: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    latency_s: float = 0.0
    limits_hit: list[str] = field(default_factory=list)
    forced_finish: bool = False
    error: str | None = None


class Auditor:
    def __init__(self, model: str | None = None, effort: str = "medium", max_tool_calls: int = 16,
                 max_cost_usd: float = 0.40, max_seconds: float = 240.0, max_tokens: int = 8000,
                 client: Any = None, config_name: str = "full", task_note: str = "") -> None:  # fmt: skip
        self.model = model or config.MODEL
        check_model(self.model)
        self.effort = effort if self.model in EFFORT_MODELS else None
        self.max_tool_calls, self.max_cost_usd, self.max_seconds = max_tool_calls, max_cost_usd, max_seconds
        self.max_tokens = max_tokens
        self.client = client or anthropic.Anthropic(max_retries=3)
        self.config_name = config_name
        self.task_note = task_note

    def _create(self, messages: list, tools: list, force_verdict: bool) -> Any:
        kw: dict[str, Any] = dict(
            model=self.model, max_tokens=self.max_tokens, system=SYSTEM, tools=tools, messages=messages,
            cache_control={"type": "ephemeral"},
        )  # fmt: skip
        if self.effort:
            kw["output_config"] = {"effort": self.effort}
        if force_verdict:
            kw["tool_choice"] = {"type": "tool", "name": "submit_verdict"}
            kw.pop("output_config", None)  # forced tool use and extended thinking don't mix
        return self.client.messages.create(**kw)

    def audit(self, case_id: str, tools: CaseTools, trace_dir=None) -> Audit:
        t0 = time.monotonic()
        a = Audit(case_id, self.model, self.config_name, dt.datetime.now().isoformat(timespec="seconds"))
        usage = Usage()
        messages: list[dict] = [
            {"role": "user", "content": TASK + (f"\n\n{self.task_note}" if self.task_note else "")}
        ]
        specs = tools.specs()
        force = False
        try:
            while tools.verdict is None:
                resp = self._create(messages, specs, force)
                usage.add(resp.usage)
                messages.append({"role": "assistant", "content": resp.content})
                uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
                if not uses:
                    if force:
                        break
                    force = True
                    a.limits_hit.append("no_verdict")
                    messages.append({"role": "user", "content": "Call submit_verdict now."})
                    continue
                results = []
                for b in uses:
                    calls = sum(1 for s in a.steps if s["tool"] != "submit_verdict")
                    if b.name != "submit_verdict" and calls >= self.max_tool_calls:
                        out = {"error": "tool-call budget used up; call submit_verdict with what you have"}
                    else:
                        s0 = time.perf_counter()
                        out = tools.call(b.name, dict(b.input or {}))
                        a.steps.append({"tool": b.name, "input": dict(b.input or {}),
                                        "ms": round((time.perf_counter() - s0) * 1000, 1),
                                        "error": out.get("error")})  # fmt: skip
                    text = compact(out)
                    if len(text) > MAX_RESULT_CHARS:
                        text = text[:MAX_RESULT_CHARS] + " ...[truncated]"
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": text,
                                    **({"is_error": True} if "error" in out else {})})  # fmt: skip
                if tools.verdict is not None:
                    break
                reasons = []
                if sum(1 for s in a.steps if s["tool"] != "submit_verdict") >= self.max_tool_calls:
                    reasons.append("tool_calls")
                if cost_usd(self.model, usage) >= self.max_cost_usd:
                    reasons.append("cost")
                if time.monotonic() - t0 >= self.max_seconds:
                    reasons.append("time")
                if reasons and not force:
                    force = True
                    a.limits_hit += reasons
                    results.append(
                        {
                            "type": "text",
                            "text": "[System: limit reached. Call submit_verdict now with what you have.]",
                        }
                    )
                messages.append({"role": "user", "content": results})
        except Exception as e:
            a.error = f"{type(e).__name__}: {str(e)[:300]}"
        a.verdict = tools.verdict
        a.forced_finish = force
        a.usage = usage.as_dict()
        a.cost_usd = round(cost_usd(self.model, usage), 6)
        a.latency_s = round(time.monotonic() - t0, 2)
        if trace_dir is not None:
            trace_dir.mkdir(parents=True, exist_ok=True)
            (trace_dir / f"{case_id}-{uuid.uuid4().hex[:6]}.json").write_text(
                json.dumps({**asdict(a), "messages": _plain(messages)}, default=str)
            )
        return a


def _plain(messages: list[dict]) -> list:
    out = []
    for m in messages:
        c = m["content"]
        if isinstance(c, list):
            c = [b.model_dump() if hasattr(b, "model_dump") else b for b in c]
        out.append({"role": m["role"], "content": c})
    return out
