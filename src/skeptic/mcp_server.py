"""Skeptic's checks as an MCP server, so Claude Code (or any MCP client) can audit a strategy folder.

    skeptic-mcp            # stdio; Claude Code launches it from .mcp.json

Design (ADR 0003):
- Three tools: describe_folder, read_file, run_check. They are the bench auditor's tools minus
  submit_verdict: the client writes the verdict (the /skeptic skill fixes its format).
- Every number comes from `StrategyFolder.run`, the same check code the bench measured, with the
  folder's declared data and spread. Results are {result, caveats, evidence, provenance} JSON, caveats
  first, so a client that truncates output cuts evidence, not the warning.
- Read-only towards the folder: nothing writes to it, file reads are confined to it, and the bench
  manifest is unreachable. The folder's strategy.py is imported and executed, as any backtest would.
- Each call is appended to runs/mcp/calls.jsonl. Nothing is written to stdout (it carries the protocol).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from skeptic import __version__, config
from skeptic.agent.prompts import SYSTEM
from skeptic.agent.tools import CaseTools
from skeptic.folder import CHECKS, open_folder

log = logging.getLogger("skeptic.mcp")
AUDIT_LOG: Path = config.RUNS_DIR / "mcp" / "calls.jsonl"

# The measured system prompt, with the two references to submit_verdict replaced: here the client writes
# the verdict. Everything else (method, flaw classes, verdict rules) is the text the bench measured.
_SWAPS = {
    "- Finish by calling submit_verdict exactly once.": "- Finish with a verdict: REJECT or SURVIVES CHECKS, "
    "one flaw class, file:line for a code flaw, and the check results that support it.",
    "Run deterministic checks.": "Run deterministic checks (run_check).",
}


def instructions() -> str:
    text = SYSTEM
    for old, new in _SWAPS.items():
        if old not in text:  # the prompt changed: fail loudly rather than serve a half-edited rulebook
            raise RuntimeError(f"prompt drift: {old!r} not found in SYSTEM")
        text = text.replace(old, new)
    return text + (
        "\n\nEvery tool takes `folder`, the strategy folder (strategy.py + params.json with a data entry). "
        "Call describe_folder first."
    )


_FOLDER = {
    "type": "string",
    "description": "Path to the strategy folder (absolute, or relative to the project).",
}
TOOLS: dict[str, dict[str, Any]] = {
    "describe_folder": {
        "title": "Describe a strategy folder",
        "description": (
            "List the folder's files and show what would be audited: the strategy contract (positions or "
            "brackets), the parameters, the declared data source (bars, date range) and the spread. Runs no check."
        ),
        "schema": {"folder": _FOLDER},
        "required": ["folder"],
    },
    "read_file": {
        "title": "Read a file in the strategy folder",
        "description": (
            "Read a text file inside the strategy folder with line numbers (cite these as file:line). "
            "At most 400 lines per call; use start_line to page."
        ),
        "schema": {
            "folder": _FOLDER,
            "path": {"type": "string", "description": "Relative path inside the folder."},
            "start_line": {"type": "integer", "minimum": 1},
        },
        "required": ["folder", "path"],
    },
    "run_check": {
        "title": "Run one deterministic check",
        "description": (
            "Run one check on the strategy with its declared data and spread. Every number in a verdict must "
            "come from these results. future_blind (truncation test for look-ahead), backtest (net expectancy, "
            "day-clustered CI), costs (break-even spread), random_entry (same exits, random entries), "
            "multiple_test (deflated Sharpe; needs n_trials from the notes or params), stability (time folds), "
            "sessions (where the PnL comes from). Results are cached per folder contents."
        ),
        "schema": {
            "folder": _FOLDER,
            "name": {"type": "string", "enum": list(CHECKS)},
            "n_trials": {
                "type": "integer",
                "minimum": 1,
                "description": "multiple_test only: configurations tried.",
            },
        },
        "required": ["folder", "name"],
    },
}


def mcp_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name=name,
            title=t["title"],
            description=t["description"],
            inputSchema={
                "type": "object",
                "properties": t["schema"],
                "required": t["required"],
                "additionalProperties": False,
            },
            annotations=types.ToolAnnotations(
                title=t["title"],
                readOnlyHint=True,  # nothing writes to the folder (the strategy code does run)
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
        for name, t in TOOLS.items()
    ]


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Run one tool. Errors come back as {"error": ...} so the client can recover."""
    try:
        folder = open_folder(args["folder"])
        if name == "describe_folder":
            return folder.describe()
        if name == "read_file":
            ct = CaseTools(folder.root, lambda *_: {}, allowed=["read_file"])
            return ct.call("read_file", {k: v for k, v in args.items() if k in ("path", "start_line")})
        if name == "run_check":
            return folder.run(args["name"], args.get("n_trials"))
        return {"error": f"unknown tool {name!r}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e).splitlines()[0][:300] if str(e) else ''}"}


def result_text(result: dict[str, Any]) -> str:
    ordered = {k: result[k] for k in ("error", "result", "caveats", "evidence", "provenance") if k in result}
    ordered |= {k: v for k, v in result.items() if k not in ordered}
    return json.dumps(ordered, separators=(",", ":"), default=str)


def _audit(entry: dict[str, Any]) -> None:
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError as e:  # the log must never break a tool call
        log.warning("could not write audit log: %s", e)


def build_server() -> Server:
    server: Server = Server("skeptic", version=__version__, instructions=instructions())
    tools = mcp_tools()

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return tools

    @server.call_tool()  # the SDK validates arguments against inputSchema before we see them
    async def _call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        t0 = time.perf_counter()
        result = await anyio.to_thread.run_sync(lambda: call(name, arguments))
        _audit({"ts": dt.datetime.now().isoformat(timespec="seconds"), "tool": name, "arguments": arguments,
                "ms": round((time.perf_counter() - t0) * 1000, 1), "result": result.get("result"),
                "error": result.get("error")})  # fmt: skip
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=result_text(result))], isError="error" in result
        )

    return server


async def serve_stdio() -> None:
    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    if argv or sys.argv[1:]:
        sys.exit("skeptic-mcp takes no arguments; it speaks MCP over stdio")
    anyio.run(serve_stdio)


if __name__ == "__main__":
    main()
