# ADR 0002: Truncation invariance is the leak test; code reading locates the leak

**Status:** accepted · **Phase:** P2

## Context
Look-ahead leaks take many forms: `shift(-1)`, centred windows, statistics over the full sample, higher-timeframe values used before that bar closes, models fitted or features selected on all data. Hunting each pattern in code is open-ended, and an LLM reading code will miss some.

## Decision
- **One behavioural test covers them all.** `future_blind` re-runs the strategy on data truncated at five cut points (40–90% of the sample). It rejects if any decision made before a cut changes. A strategy that decides at bar t from bars ≤ t is unaffected by deleting later bars, by construction. Every leak class above changes some past decision.
- **The test says *that* a strategy leaks, not *where*.** Locating the line is the agent's job, from the code. The bench scores that separately (flaw class, and file:line within ±3 lines).
- Tested: passes a leak-free fade strategy (position and bracket form); rejects `shift(-1)`, a centred window and full-sample z-scores.

## Consequences
- A "rules only" baseline will catch most leaks without any LLM. The eval must therefore credit the agent for localisation and for flaws the test can't see, such as an unrecorded parameter search or a research write-up that breaks its own rules, not for detection the test already does.
- Strategies must be deterministic given their input; a seeded random component is fine, an unseeded one fails the test (correctly: it can't be audited).
- Cost: one full run plus five truncated runs per check.

## Alternatives considered
- **Static pattern matching** (grep for `shift(-`, `center=True`, `.fit(` on full frames): cheap, but it misses indirect forms (a helper function, a resample with the wrong label) and flags harmless uses.
- **Comparing live vs backtest signals:** the gold standard in production, but it needs a live record, which the bench cannot have. The case study uses Aziz's 25 live signals for exactly this (his §0 gate).
