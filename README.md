# Skeptic

**A research agent whose only job is to kill trading strategies. It reads the code and the research notes, runs look-ahead, cost, random-entry and multiple-testing checks, and returns REJECT or SURVIVES CHECKS with file:line evidence. It is measured on 90 strategies with planted flaws and planted real edges.**

[![ci](https://github.com/azb27/skeptic/actions/workflows/ci.yml/badge.svg)](https://github.com/azb27/skeptic/actions/workflows/ci.yml)

- On **verdicts**, Claude Sonnet 5 with the checks gets **97%** right, and fixed rules with no LLM get **94%**. That gap is not significant (p = 0.73). The checks do most of the catching.
- What the model adds is **why and where**. It names the right flaw class in **88%** of cases against the rules' 49%, and puts its finger on the leaking line in **89%** of leaks against 0%. For the 13 leaks the look-ahead probe cannot see, it rejected all 13 and located 10.
- **The checks are what let a model say yes.** The same model reading code without the checks rejected **25 of 30 genuine edges**.
- It never says "profitable". The strongest verdict is **SURVIVES CHECKS**: these checks found nothing.

```text
$ skeptic audit examples/fade_leaky
REJECT  [centered_window]  (strategy.py:9)

The "typical move" baseline is computed with `rolling(params["span"], center=True, ...)`, a centered window
that uses future bars to judge whether the current move is a "shock" — a clear look-ahead leak. future_blind
confirms this: truncating the data at various cut points changes decisions near the cut (e.g. 22 of 24561
decisions changed at the 2023-05-04 cut), proving the signal depends on bars not yet seen. Although backtest,
costs, and random_entry all pass on this leaky signal (mean 0.8332 USD/trade, CI [0.6676,1.0042], survives
$0.50 spread, beats random entries p=0.002), these results are invalidated by the demonstrated leak [...]

9 tool calls, $0.022, 15s, model claude-sonnet-5
```
*A real run on the bundled example, unedited apart from line wrapping and the cut marked [...]. Next to its leak-free twin (`examples/fade_clean`), the leak raises the backtest mean and the break-even spread and leaves the other checks passing. That is why leaks survive review.*

## The problem
A backtest is a claim, and most claims are wrong for boring reasons:
- **Look-ahead:** a `shift(-1)`, a centred window, a z-score over the whole sample, an hourly bar used before it closes, or a model fitted on the data it then trades.
- **Costs:** a gross edge smaller than the spread.
- **Luck:** entries no better than random entries with the same exits.
- **Search:** the best of 200 parameter sets, presented as if it were the only one.

I built Skeptic after my own history taught me this. An earlier XAUUSD model of mine reported high directional accuracy, but directional accuracy is not profit and that code is gone, so the claim can never be checked. My rule-based gold system went the other way: I pre-registered its tests, and they failed. Skeptic audits that system below.

## What it checks
Every number comes from one of these checks. The model chooses which to run, reads the code to find the cause, and writes the verdict; it never computes a statistic.

| Check | Rejects when |
|---|---|
| `future_blind` | Deleting future bars changes any past decision. It cuts at 5 even points plus up to 25 bars where the strategy's decision changes. A REJECT proves a leak; a PASS doesn't prove there isn't one (it missed 13 of the bench's 35). |
| `backtest` | The net expectancy's 95% interval (resampling whole days) includes zero or sits below it. Position strategies fill at the next bar's open; bracket strategies enter at the signal bar's close (or the next open) and count ambiguous bars as stops. The spread is charged on every trade. |
| `costs` | The break-even spread is below the realistic spread. |
| `random_entry` | 500 random-entry runs with the same exits do as well. |
| `multiple_test` | The deflated Sharpe ratio, given the number of configurations tried, is below 0.95. PBO by CSCV runs when the grid is logged. |
| `stability` | Most of five time folds lose money. |
| `sessions` | Information only: where the PnL comes from. |

## Results
All numbers below come from generated reports.

**The bench** has 90 synthetic strategies with known truth:
- 30 real edges
- 35 look-ahead leaks across 7 classes
- 10 multiple-testing traps
- 5 edges killed by costs
- 10 honest strategies with no edge

An oracle confirms every non-leak case (the edge clears the checks, the null fails, and so on). Leaks are leaks by construction. Scoring is deterministic, with no LLM judge. [Full report](docs/results/bench.md) · [failure analysis](docs/results/failure-analysis.md).

| Configuration | Verdict correct [95% CI] | Right reason | Leak line found | Real edges rejected | $ / case |
|---|---|---|---:|---:|---:|
| Rules only (checks, fixed thresholds) | 94% [89, 99] | 49% [47, 50] | 0% | 0 / 30 | 0 |
| **Sonnet 5: code + checks** | **97%** [92, 100] | **88%** [81, 94] | **89%** | 3 / 30 | $0.025 |
| Haiku 4.5: code + checks | 96% [91, 99] | 83% [76, 90] | 71% | 3 / 30 | $0.027 |
| Sonnet 5: checks only, no code | 91% [84, 97] | 76% [67, 83] | 0% | 3 / 30 | $0.014 |
| Sonnet 5: code only, no checks | 71% [67, 77] | 52% [47, 58] | 91% | 25 / 30 | $0.023 |

What the failures say:
- **Sonnet's three errors are one pattern.** It rejected real edges as `process` because the parameters in the notes differed from the code's defaults, even though every check passed.
  - Each case rerun three times came back correct 7 of 9 times ([repeats](docs/results/repeats.md)), so this is an intermittent judgement call, not a systematic blind spot.
  - I didn't change the bench or the scorer to make it go away. One earlier bench fix in this area, made after a pilot and before any reported run, is logged in [CORRECTIONS #1](evals/CORRECTIONS.md).
- **Haiku's errors are worse.** All three of its false rejects claim a leak the probe had just cleared.
- **Without the code, the model can't find a leak the probe misses.** Without the checks, it rejects almost everything.

**The shipped path,** Claude Code + `/skeptic` + the MCP server, was run on 20 cases fixed in advance, each staged as an ordinary strategy folder. It got **20 of 20** verdicts right, 20 of 20 for the right reason, and found the leak line in 8 of 8 leaks, with no tools used outside the server ([transcript table](docs/results/claude_code_skill_p7.md)). The API auditor also got 20 of 20 on these cases, so this shows the shipped path holds up, not that it beats the API loop. Twenty cases is a smoke test, not a second benchmark.

## Case study: auditing my own gold system
Gold Sniper v5.3 is a rule-based intraday XAUUSD system I wrote in Pine: ICC phases, fair-value gaps, killzones, and 1:1 targets. In September 2026 I pre-registered three ways to improve it ([pre-registration](case_study/PREREGISTRATION.md)). All three failed, and the base system lost **−0.123R per trade at a $0.50 spread** ([results](case_study/RESULTS.md)). That run's own fidelity gate was unmet, so its numbers were formally provisional.

Skeptic re-ran my harness on an independent public feed, then ran its own checks on it ([full write-up](docs/case-study-gold-sniper.md)):

| | Original run | My harness, independent feed (Sep 2024 – Jan 2026) | Skeptic's `backtest` on the same signals |
|---|---:|---:|---:|
| Trades | 2,092 | 1,146 | 1,146 |
| Hit rate at 1:1 | 49.67% | 49.7% | 50.6% |
| Net per trade at $0.50 spread | −0.123R | **−0.118R** [−0.176, −0.063] | **−0.114R** [−0.172, −0.060] |

- **No look-ahead.** `future_blind` passed at 30 cut points.
- **No edge.** Backtest, costs (break-even spread $0.05), random entry (p = 0.21) and stability all reject. Skeptic's engine agrees with my harness on 99.7% of trade outcomes; the hit rates differ because Skeptic's engine counts a trade by its sign after costs, not by whether it reached the first target.
- **The auditor's verdict** was REJECT, `no_edge`, for $0.05.
- **What it missed.** The auditor judged my research process sound, and it wasn't entirely. The pre-registration's out-of-sample rule wasn't recorded as followed, a second fidelity gate (ADX error) failed unremarked, and two live-trade counts (25 and 29) appear without saying which one the gate was judged on. None changes the conclusion, but an auditor that only confirms the author isn't doing its job. That gap is the next bench group (SPEC §5, write-up only).

The harness that runs the system is private; the repo publishes the audit, aggregates and short excerpts. The broker's name is redacted in the two write-ups.

## Use it on your own strategy
A strategy folder needs a `strategy.py` (`positions(bars, params)` returning -1/0/+1 per bar, decided at the bar's close; or `signals()` for stop/target brackets) and a `params.json`:

```json
{
  "params": {"k": 3.0, "span": 100, "hold": 6},
  "data": {"source": "file", "path": "bars.csv"},
  "spread_usd": 0.30,
  "n_trials": 12
}
```

| `data.source` | Bars |
|---|---|
| `file` | A CSV or Parquet file inside the folder with columns `ts, open, high, low, close` (UTC, bar open time) and at least 500 bars. It must declare `spread_usd`. |
| `xauusd` | The public 1-minute XAUUSD mirror, `"timeframe": "5min"` or `"1h"`, with optional `start` and `end`. Run `python -m skeptic.data` first (~150 MB). |
| `synthetic` | A seeded synthetic market (`seed`, `n_days`), for trying it out. |

Optional keys: `n_trials` (configurations tried) and `grid` (the list of parameter sets, which turns on PBO). Bracket strategies can also set `entry` (`"close"` or `"open"`) and `max_bars` (the timeout).

Add your research notes as `.md` files. The auditor reads them for trial counts and process. If you don't set `n_trials`, a parameter search goes unrecorded, and that's reported as a caveat, not a pass.

```bash
git clone https://github.com/azb27/skeptic && cd skeptic && pip install -e .

skeptic describe my_strategy/                    # what would be audited: contract, data, spread
skeptic check my_strategy/ future_blind          # one deterministic check, no API key needed
skeptic audit my_strategy/                       # the bench-measured auditor (ANTHROPIC_API_KEY, ~$0.03)
```
Exit codes: `0` SURVIVES CHECKS (or a single check that didn't reject), `1` REJECT, `2` any error, including a crash in your strategy. To gate a research repo in CI, use `skeptic audit`: a single `check` can return INFO, for example `multiple_test` with no trial count, and INFO exits `0`.

**In Claude Code**, open this repo and type `/skeptic my_strategy/`. The repo's `.mcp.json` starts `skeptic-mcp`. To use it from any project:
```bash
claude mcp add --scope user skeptic -- "$(which skeptic-mcp)"   # absolute path, so a venv install works
cp -r .claude/skills/skeptic ~/.claude/skills/
```
Claude Desktop and other MCP clients can launch `skeptic-mcp` the same way; the server's instructions carry the audit rules.

`skeptic` runs your `strategy.py`, as any backtest does, so only point it at code you trust. Skeptic writes nothing to your folder (not even a bytecode cache), file reads stay inside it, and every check result carries its provenance: data, date range, spread, engine and seed.

## How it works
```
 strategy folder  ──read-only──>  auditor (Messages API loop, or Claude Code + /skeptic)
   strategy.py                      reads code + notes, chooses checks      ──> REJECT | SURVIVES CHECKS
   params.json (data, spread)                │                                   flaw class, file:line,
   research notes                            ▼                                   evidence from checks
                         checks: plain Python, unit-tested; the only source of numbers
                         future_blind · backtest · costs · random_entry · multiple_test · stability · sessions
```
- **Synthetic bench, real truth.** Markets have GARCH-style volatility, session seasonality and an optional planted edge: mean reversion after a shock. The strategy templates come in several code styles, so the model can't pattern-match a single file. The manifest is readable only by `tests/` and `evals/`.
- **Two engines.** A position engine fills at the next bar's open. A bracket engine resolves stops and targets with ambiguous bars counted as stops. Costs are always explicit and never default to zero.
- **Decisions:**
  - [ADR 0001](docs/adr/0001-explicit-costs-next-bar-fills-pessimistic-ambiguity.md): explicit costs, next-bar fills, pessimistic ambiguity.
  - [ADR 0002](docs/adr/0002-truncation-invariance-as-the-leak-test.md): truncation invariance as the leak test.
  - [ADR 0003](docs/adr/0003-ship-as-folder-contract-plus-mcp-checks.md): folder contract, MCP and the skill.
- **Bugs found in the bench and checks** while running them are logged in [`evals/CORRECTIONS.md`](evals/CORRECTIONS.md). That includes a probe false alarm my own harness exposed.

## Limits
- **It can only fail to reject.** SURVIVES CHECKS means these checks found nothing. It doesn't mean the strategy makes money, and it says nothing about flaw types outside the bench's classes.
- **The bench is synthetic.** It proves detection of planted flaws with known locations, not of every artefact real data has: survivorship, bad ticks, broker-specific fills.
- **Each configuration ran once.** The intervals resample cases, not model runs, and reruns show verdicts on borderline cases can flip.
- **The checks are gold-shaped.** The session labels, the CME trading day and the $0.50 default spread all assume XAUUSD. Other instruments work through a `file` source with their own spread, with UTC days as trading days unless the file supplies them.
- **The auditor checks numbers better than process.** It confirmed my research process when it should have questioned it.

## Repo map
```
src/skeptic/      backtest.py (engines) · checks.py · synth.py · folder.py (your folder) · cli.py · mcp_server.py · agent/
bench/            templates.py · build.py · cases/ (90 folders) · manifest.json (ground truth; evals and tests only)
evals/            rules_baseline · run_agent · report · repeat · p7_claude_code · case_study · CORRECTIONS.md
docs/             results/ (generated) · adr/ · case-study-gold-sniper.md
examples/         fade_clean, fade_leaky: two folders to try without any download
case_study/       the pre-registration and results for Gold Sniper v5.3
runs/             per-case results of every reported run (traces stay local)
```
```bash
pip install -e ".[dev]" && pytest -q        # 55 tests; data-dependent ones skip without the XAUUSD download
python -m evals.report                       # rebuild docs/results/bench.md from the published runs/evals/*/results.jsonl (no API calls)
```
