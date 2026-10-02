"""The MCP server exposes the bench auditor's read and check tools, nothing more, with the same numbers."""

from __future__ import annotations

import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from skeptic import config, mcp_server
from skeptic.agent.prompts import SYSTEM
from skeptic.agent.tools import SPECS
from skeptic.folder import StrategyFolder

pytestmark = pytest.mark.anyio
EX = config.ROOT / "examples"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def log_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "AUDIT_LOG", tmp_path / "calls.jsonl")


async def _call(name: str, args: dict):
    async with create_connected_server_and_client_session(mcp_server.build_server()) as s:
        r = await s.call_tool(name, args)
    return r, json.loads(r.content[0].text)


async def test_catalogue_is_read_and_check_tools_only():
    async with create_connected_server_and_client_session(mcp_server.build_server()) as s:
        tools = (await s.list_tools()).tools
    assert [t.name for t in tools] == ["describe_folder", "read_file", "run_check"]
    assert all(t.annotations.readOnlyHint and not t.annotations.destructiveHint for t in tools)
    check_enum = next(t for t in tools if t.name == "run_check").inputSchema["properties"]["name"]["enum"]
    assert check_enum == SPECS["run_check"]["input_schema"]["properties"]["name"]["enum"]


def test_instructions_are_the_measured_rules():
    text = mcp_server.instructions()
    method = SYSTEM.split("How to audit")[1]  # method, flaw classes and verdict rules: unchanged
    assert method in text and "submit_verdict exactly once" not in text


async def test_run_check_matches_the_library():
    r, body = await _call("run_check", {"folder": str(EX / "fade_leaky"), "name": "future_blind"})
    assert not r.isError and body["result"] == "REJECT"
    assert list(body)[:3] == ["result", "caveats", "evidence"]  # caveats before evidence
    direct = StrategyFolder(EX / "fade_leaky").run("future_blind")
    assert body["evidence"] == json.loads(json.dumps(direct["evidence"], default=str))


async def test_read_file_is_confined_to_the_folder():
    r, body = await _call("read_file", {"folder": str(EX / "fade_clean"), "path": "strategy.py"})
    assert not r.isError and "   1| " in body["content"]
    r, body = await _call(
        "read_file", {"folder": str(EX / "fade_clean"), "path": "../fade_leaky/strategy.py"}
    )
    assert r.isError and "outside the case folder" in body["error"]


async def test_bad_input_is_a_recoverable_error():
    r, body = await _call("describe_folder", {"folder": "/nonexistent/strategy"})
    assert r.isError and "not a folder" in body["error"]
    async with create_connected_server_and_client_session(mcp_server.build_server()) as s:
        bad = await s.call_tool("run_check", {"folder": str(EX / "fade_clean"), "name": "optimise"})
    assert bad.isError  # the schema enum refuses checks that don't exist


async def test_calls_are_logged(tmp_path):
    await _call("describe_folder", {"folder": str(EX / "fade_clean")})
    rows = [json.loads(x) for x in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert rows[-1]["tool"] == "describe_folder" and rows[-1]["error"] is None
