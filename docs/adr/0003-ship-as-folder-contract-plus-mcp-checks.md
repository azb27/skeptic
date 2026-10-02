# ADR 0003: Ship as a folder contract, with the checks behind MCP and the verdict in the client

**Status:** accepted · **Phase:** P7

## Context
The bench measured one harness: a Messages API loop with read, check and `submit_verdict` tools, where a bench case's market comes from the manifest. A stranger has neither the bench's markets nor that loop. They have a folder with a strategy and some notes, their own prices, and usually Claude Code.

## Decision
- **A folder declares its data and spread** in `params.json` (`xauusd`, a CSV/Parquet `file` inside the folder, or a seeded `synthetic` market). `StrategyFolder` loads it and runs the same check functions the bench ran. A file source must state `spread_usd`; gold-scale sources default to $0.50 with a caveat. Costs stay explicit (rule 3).
- **Two front doors over one engine.** `skeptic audit <folder>` runs the bench auditor unchanged (same prompt, tools and caps). `skeptic-mcp` exposes `describe_folder`, `read_file` and `run_check` to any MCP client, and the `/skeptic` skill tells Claude Code how to use them and how to write the verdict. The server's instructions are the measured system prompt with only the `submit_verdict` lines swapped, and a test fails if that prompt drifts.
- **The numbers stay out of the model.** Check results carry provenance (data, bars, date range, spread, engine, seed, folder fingerprint) and are cached per folder contents, so editing `strategy.py` invalidates them.
- **The manifest stays unreachable.** Bench case folders have no `data` entry, file reads are confined to the folder, and the manifest path is refused outright (tested).
- **The shipped path is measured, not assumed.** `evals/p7_claude_code.py` stages 20 pre-selected bench cases as ordinary folders and runs `/skeptic` through headless Claude Code with only the MCP tools.

## Consequences
- The skill path is a different harness from the bench run (Claude Code's system prompt, its own tool loop, no forced verdict at a cap), so the bench numbers do not transfer automatically. The 20-case run checks they roughly hold; it is a smoke test, not a second benchmark.
- `run_check` executes the folder's `strategy.py`. That is inherent to backtesting, and it is the user's own code, but it means the MCP server should only be pointed at code the user trusts. The README says so.
- The check suite is gold-shaped (session labels, CME trading day). Other instruments work through a file source, with UTC days as trading days unless the file supplies them.

## Alternatives considered
- **Expose a single `audit(folder)` MCP tool that runs the API loop inside the server.** It would carry the bench numbers over exactly, but it hides the reasoning from the user's client, needs a second API key inside the server, and pays for a model call inside a model call. Kept as the CLI instead.
- **Let Claude Code read files with its own Read tool.** Simpler for Claude Code users, but Claude Desktop has no file access, and confinement would then depend on the client's permissions rather than the server's. The skill pre-allows only the three MCP tools.
- **Ship no default spread at all.** Purer, but most users of a gold-specific tool would hit an error on their first call. The default is stated as an assumption in every result.
