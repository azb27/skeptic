# Skeptic: build spec

> A research agent whose only job is to kill trading strategies. It reads a strategy's code and research notes, runs leakage, cost and multiple-testing checks, and returns a verdict with evidence: **REJECT** or **SURVIVES CHECKS**. It never says "profitable". It is itself measured on a bench of strategies with planted flaws and planted real edges, with confidence intervals.

**Thesis this project proves:** *I can tell a real edge from a backtest artefact, and I can measure how reliably a tool (or an LLM) does it.*

**Target reader:** a quant researcher or quant-dev lead, and an AI-engineering lead who wants to see an LLM evaluated against ground truth rather than vibes. They spend 90 seconds on the README and 5 minutes on the bench results.

---

## 1. The story the repo tells (and the honest part)

- Aziz's earlier XAUUSD work reported high directional accuracy on walk-forward validation. Directional accuracy is not PnL, and the code for that pipeline no longer exists, so the claim can't be re-checked. Skeptic exists so that never happens again: every claim gets audited by a tool that is trying to break it.
- **The case study** is Aziz's own XAUUSD Gold Sniper v5.3: a rule-based intraday system (ICC phases, fair-value gaps, killzones, multi-timeframe bias) written in Pine, and its **pre-registered replay audit** (`case_study/PREREGISTRATION.md`, `case_study/RESULTS.md`, 25 Sep 2026).
  - **The audit found:** 2,092 trades on two years of 5-minute spot, a 49.67% hit rate at 1:1, and **+0.007R per trade before spread** but **−0.123R at a $0.50 spread** (95% CI −0.168 to −0.078). All three hypotheses failed their locked promotion rules.
  - **The audit also records its own gate as unmet.** The harness reproduced 18 of 25 live signals, against ≥ 23 required, so every number is formally provisional.
- **Skeptic's job on the case is to audit the audit, not rediscover it:**
  1. Read the write-ups and check that each claim follows from the documents' own rules: gates, out-of-sample discipline, trial counts, and whether the arithmetic adds up.
  2. Re-run the replay on an independent feed (public 1-minute XAUUSD, 2009–2026) with its checks, including the random-entry baseline. Is 49.67% at 1:1 distinguishable from random entries with the same exits?
  3. State what the evidence supports. A third feed agreeing makes a provisional negative much firmer; a disagreement must be explained.
- **The bench is the headline**, not the case study. One audit is an anecdote; a measured detection rate is evidence.

## 2. Architecture

```
  strategy case/                    Skeptic agent (Anthropic Messages API loop, caps on calls/$/time)
    strategy.py   ── read-only ──>    reads code + notes          ──> submit_verdict (structured):
    research_log.md                   calls deterministic checks       verdict, flaw class, file:line,
    params.json                              │                          evidence list
                                             ▼
                     checks (plain Python, unit-tested; the LLM never computes a statistic)
                     ├── backtest      next-bar-open execution, spread + slippage, R and PnL
                     ├── future_blind  re-run on data truncated at k cut points; any change in past
                     │                 positions = the strategy reads the future
                     ├── random_entry  same exits and holding, random entries: is the edge > noise?
                     ├── costs         break-even spread vs a realistic spread
                     ├── multiple_test deflated Sharpe ratio; PBO via CSCV when a grid is logged
                     ├── walk_forward  purged, embargoed splits for anything that fits a model
                     └── sessions      Asia / London / NY breakdown: one session carrying it all?

  bench/  planted flaws + planted edges on synthetic markets ── ground-truth manifest (evals only)
  data/   XAUUSD M1 2009–2026 (HistData format, public HF mirror) -> H1 / M5 bars (case study only)
```

- **The LLM never produces a number.** Every statistic comes from a check; the agent decides which checks to run, reads code to locate a flaw, and writes the verdict. Same rule as Stockroom: numbers come from tools.
- **The agent can only fail to reject.** "SURVIVES CHECKS" means the listed checks found nothing, not that the strategy makes money. The README says so.
- **Read-only.** The agent can read the case folder and run checks. It cannot write files, edit strategies, or search for better parameters. Optimising is out of scope by design.

## 3. Strategy contract

A case is a folder with `strategy.py` (code) and/or research write-ups (`*.md`: pre-registrations, results, logs). `strategy.py` exposes:
```python
def positions(bars: pd.DataFrame, params: dict) -> pd.Series:
    """Target position in {-1, 0, +1} per bar, decided at that bar's close."""
```
- The engine executes at the **next bar's open** and charges spread plus slippage on every change. Strategies cannot choose their own fills.
- Optional: `research_log.md` (what was tried), `params.json` (chosen params, and a grid if one was searched).
- ML strategies fit inside `positions()` and must refit on an expanding window to pass `future_blind`.

## 4. Checks (contracts)

Every check returns `{result, evidence, caveats}`. Defaults are in `config.py`.

| Check | Rejects when | Notes |
|---|---|---|
| `future_blind` | Positions before a cut point change when data after it is removed (5 cut points) | Catches shift(-1), centred windows, full-sample normalisation, higher-timeframe values used before that bar closes, fitting or selecting on the full sample. It says *that* the strategy leaks, not *where*. |
| `backtest` | Net expectancy CI includes 0 or is below 0 | Trade-level bootstrap; R multiple and PnL per trade; Sharpe |
| `costs` | Break-even spread < realistic spread (default: $0.50 XAUUSD) | Gross-positive / net-negative is the commonest real failure |
| `random_entry` | Strategy's net expectancy is inside the 95% band of 500 random-entry runs with the same exits | Separates entry skill from exit/regime luck |
| `multiple_test` | Deflated Sharpe < 0.95 given the logged number of trials; PBO > 0.5 when a grid is logged | Trials come from `research_log.md`/`params.json`. Unlogged trials are a caveat, not a pass. |
| `walk_forward` | Out-of-sample net expectancy ≤ 0 across purged, embargoed folds | Only for strategies with fitted parameters |
| `sessions` | (informational) one session carries > 80% of PnL | A caveat, never a rejection by itself |

## 5. The bench (ground truth)

Synthetic markets (seeded): GARCH-style volatility, intraday session seasonality, optional planted edge (post-shock mean reversion with tunable strength). Strategy templates are written in several code styles so the agent can't pattern-match one file.

| Group | Ground truth | What's planted | n |
|---|---|---|---:|
| Real edge, clean code | SURVIVES | Edge strong enough to clear costs; leak-free | 30 |
| No edge, clean code | REJECT | Null market, honest strategy | 10 |
| Leaks (7 classes × 5) | REJECT | `shift(-1)`, centred window, full-sample z-score, HTF lookahead, random K-fold without purge, feature selection on full sample, fill-forward from the future | 35 |
| Multiple testing | REJECT | Best of N parameter combos on a null market, N logged | 10 |
| Killed by costs | REJECT | Real but small edge, high turnover | 5 |
| Write-up only (stretch) | REJECT / SURVIVES | Research reports with a planted process flaw: out-of-sample peeked before the decision, failed gate treated as passed, trial count understated, accuracy reported instead of PnL, costs omitted. Clean controls follow their own rules. | 20 |

- The manifest (verdict, flaw class, file:line) lives in `bench/manifest.json`, readable only by tests and evals (same rule as Stockroom's ground truth).
- **Scoring is deterministic**, from the structured verdict: verdict correct; flaw class correct; location within ±3 lines of the planted flaw. No LLM judge.

## 6. Evaluation (the headline)

| Config | What it isolates |
|---|---|
| **Rules only** (checks with fixed thresholds, no LLM) | The baseline. If the agent can't beat it on something, say so. |
| Sonnet agent: code + checks | The full system |
| Haiku agent: code + checks | Cost/accuracy trade-off |
| Sonnet: checks only, no code access | What reading code adds (localisation, flaw class) |
| Sonnet: code only, no checks | What the checks add (the LLM alone vs statistics) |

**Report:**
- Verdict accuracy, false-reject rate on real edges and miss rate on flaws, each with a bootstrap CI.
- Flaw-class accuracy and localisation rate.
- McNemar between configs.
- $ per case and p50 latency.

**Expected and fine:** rules-only may match the agent on verdicts, because `future_blind` catches most leaks. The agent's value would then be localisation, explanation and the multiple-testing reading of research logs. The report says whichever is true.

## 7. Phases

- [ ] **P0: Scaffold.** Repo, `CLAUDE.md`, ADR template, CI (lint + tests), data fetch from the public HF mirror, M1 → H1/M5 bars with session labels.
- [ ] **P1: Backtest engine + costs.** Next-bar-open execution, spread/slippage, trade list, R and PnL, trade-level bootstrap.
  - *Done:* engine tests with hand-computed trades.
- [ ] **P2: Checks.** `future_blind`, `random_entry`, `costs`, `multiple_test` (DSR, PBO via CSCV), `walk_forward` (purged/embargoed), `sessions`.
  - *Done:* each check has a test with a planted positive and a planted negative.
- [ ] **P3: Bench.** Synthetic market generator, strategy templates, flaw injectors, manifest. Rules-only baseline scored.
- [ ] **P4: Agent.** Messages API loop (port of Stockroom's), read-only file tools, check tools, `submit_verdict` with a JSON schema. Traces.
- [ ] **P5: Eval.** All configs, report with CIs, failure analysis with traces.
  - *Budget:* about $15–30 of API credit for all configs. A run cap is set before starting.
- [ ] **P6: Case study.**
  - Obtain Aziz's harness (the Python re-implementation of v5.3), or port the Pine logic if it's lost, and record which.
  - Reproduce the baseline on the independent feed. Then audit the code and the two write-ups, and write `docs/case-study-gold-sniper.md`.
  - The harness is private code. The repo publishes the audit and excerpts, not the harness.
- [ ] **P7: Ship.** README (problem → bench table → case study → limits), MCP server + Claude Code skill so anyone can run `/skeptic` on their own strategy folder.

## 8. Out of scope

- Finding, optimising or recommending strategies. Skeptic only tries to break them.
- Live trading, broker integration, Pine execution.
- Proving profitability. "Survives checks" is the strongest statement it makes.
- Unknown flaw classes. The bench measures the seven planted classes plus multiple testing and costs; a pass says nothing about flaws outside that list.

## 9. Data honesty

- Case-study prices: XAUUSD 1-minute bars in HistData format, from a public Hugging Face mirror (`fokan/xauusd-2009-2026`). They're downloaded by script and never committed. Broker prices differ in spread and gaps; the cost check uses explicit spread assumptions, stated in every report.
- Bench markets are synthetic, so ground truth is known exactly. That proves detection of the planted classes, not of every real-world artefact.
