# ADR 0001: Explicit costs, next-bar fills, pessimistic ambiguity

**Status:** accepted · **Phase:** P1

## Context
Most backtest flattery comes from three places: no costs, filling at a price you couldn't have had, and resolving a bar that touched both stop and target in your favour. Skeptic's credibility depends on its own engine not doing any of these.

## Decision
- **Costs are a required argument.** Neither engine has a default spread, so "gross" and "net" can't be confused. Results are reported at $0.20 / $0.50 / $0.90 round trip for XAUUSD; $0.50 decides, matching Aziz's pre-registration.
- **Position engine:** a target position decided at bar t's close fills at bar t+1's open. Strategies can't choose fills.
- **Bracket engine:** entry at the signal bar's close (what an alert-driven trader gets) or the next open. Exits are resolved only on later bars. A bar that touches both stop and target counts as a **stop** by default; the optimistic figure is available but must be reported alongside, never instead.
- **Uncertainty is clustered by trading day.** Many trades on one trending day are not independent evidence. Tested: on clustered data the day bootstrap is more than twice as wide as the naive one.

## Consequences
- Results are conservative. A strategy that only works with optimistic ambiguity or same-bar fills is reported as such.
- Bracket trades are resolved independently, so overlapping trades are allowed. Cooldowns and position limits belong to the strategy, which is where the case-study system keeps them.

## Alternatives considered
- **An off-the-shelf backtester** (vectorbt, backtrader): less code, but its defaults would then be part of every verdict, and auditing an auditor's dependencies is a worse story than 150 tested lines.
- **Tick-level resolution of ambiguous bars:** more accurate, but the public feed is 1-minute bid only, so it would add precision the data doesn't support. Pessimistic plus a reported optimistic bound is honest about that.
