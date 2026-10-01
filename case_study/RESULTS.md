# Harness Run 1 — Results

**Date:** 25 September 2026
**Baseline:** `gold_sniper_v5_3.pine` as deployed
**Feeds:** Twelve Data XAU/USD spot, 178,133 five-minute bars, Sep 2024 – Sep 2026 (562 sessions);
COMEX GC=F, 13,539 bars, 60 days (52 sessions)
**Registered variants:** 12, each run on both feeds. No unregistered variants were run.
**Gate status:** PREREGISTRATION.md §0 signal gate **unmet** (no long broker export exists). All
results are provisional and cannot, on their own, promote a change to the live script.

---

## 1. Baseline

| Feed | Trades | Sessions | TP1 rate | Net R/trade @ $0.50 | 95% CI (session bootstrap) |
|---|---|---|---|---|---|
| Spot, 2 years | 2,092 | 562 | 49.67% | −0.1231 | (−0.168, −0.078) |
| Futures, 60 days | 167 | 52 | 49.10% | −0.0883 | (−0.245, +0.085) |

The two feeds agree, and both agree with the six live sessions (40% TP1 on 25 trades).

### Cost decomposition — the central finding

| Round-trip spread | Per trade | Total over 2,092 trades |
|---|---|---|
| $0.00 | **+0.0069R** | +14.4R |
| $0.20 | −0.0451R | −94.4R |
| $0.50 | −0.1231R | −257.6R |
| $0.90 | −0.2271R | −475.1R |

At 1:1 the break-even hit rate is 50.00%. The system delivers **49.67% over 2,092 trades**.
Gross expectancy is +0.007R — statistically indistinguishable from a coin flip. **The entire
loss is the spread.** This is not a filter-tuning problem; there is no directional edge at this
horizon and target geometry for the costs to eat into.

## 2. H1 — Re-entry after a stop-out: **FAILS**

Required: hit rate +10 percentage points and expectancy +0.15R, on ≥30 re-entries.

| Feed / split | Re-entries | Fresh | TP1 re-entry | TP1 fresh | Δ rate | Δ expectancy | p |
|---|---|---|---|---|---|---|---|
| Spot, in-sample | 285 | 1,133 | 50.88% | 49.51% | +1.4 pp | +0.031R | 0.69 |
| Spot, out-of-sample | 145 | 529 | 51.03% | 48.96% | +2.1 pp | +0.044R | 0.71 |
| Futures, in-sample | 14 | 100 | 64.29% | 47.00% | +17.3 pp | +0.355R | 0.26 |
| Futures, out-of-sample | 17 | 36 | 47.06% | 50.00% | −2.9 pp | −0.050R | 1.00 |

The live observation that generated this hypothesis was 5 of 5 re-entries winning against 5 of 20
fresh signals (Fisher p = 0.005). At 430 re-entries the effect is +1.4 to +2.1 points with p ≈ 0.7.
The futures in-sample cell reproduces the live-sized illusion — 14 trades, +17 points, not
significant — and reverses out-of-sample. **The live finding was noise.**

## 3. H2 — ADX floor: **FAILS**

Registered as a null. Required to beat floor = 20 by ≥0.10R in-sample, hold ≥0.05R out-of-sample,
have improving neighbours, and survive $0.50 spread.

| Variant | Spot IS | Spot OS | Futures IS | Futures OS |
|---|---|---|---|---|
| none | −0.1422 | −0.0492 | −0.0623 | −0.0968 |
| 15 | −0.1535 | −0.0419 | −0.0667 | −0.0836 |
| 18 | −0.1413 | −0.0548 | −0.1638 | −0.1022 |
| **20 (live)** | **−0.1487** | **−0.0693** | **−0.0889** | **−0.0869** |
| 23 | −0.1522 | −0.0519 | −0.0082 | −0.2283 |
| 25 | −0.1419 | −0.0466 | +0.0035 | −0.2541 |
| 20 + expansion override | −0.1488 | −0.0526 | −0.1608 | −0.1351 |

On the 2-year feed all seven variants sit within 0.012R of each other — the floor barely matters.
On 60 days of futures, floors of 23 and 25 look best in-sample (−0.008, +0.004) and are the two
**worst** out-of-sample (−0.228, −0.254). That inversion on the short feed, absent on the long one,
is the overfitting signature this test was designed to expose.

## 4. H3 — Killzone windows: **FAILS**

| Variant | Spot IS | Spot OS | Futures IS | Futures OS |
|---|---|---|---|---|
| **windows (live)** | **−0.1487** | **−0.0693** | **−0.0889** | **−0.0869** |
| + 14:00–16:30 UAE gap | −0.1496 | −0.0802 | −0.0732 | −0.0700 |
| 24h, no off-window penalty | −0.1394 | −0.0878 | 0.0000 | −0.0812 |
| 24h, penalty halved | −0.1558 | −0.0670 | −0.0068 | −0.1120 |

The best case is 24-hour trading on futures in-sample (+0.089R versus live, just under the 0.10
bar), which holds only +0.006R out-of-sample against a 0.05 requirement, and is +0.009R / −0.019R
on the long feed. Adding the 14:00–16:30 window helps on futures and hurts on spot. Nothing passes
on both feeds.

## 5. Consequence

PREREGISTRATION.md §5 applies: **v5.3 is frozen, threshold tuning on this instrument ends.** The
decision to make next is not a parameter; it is whether a 49.7% coin flip at 1:1 can be replaced by
an entry with actual directional edge, and what the real broker spread is.

## 6. What would change these conclusions

- A long broker XAUUSD export, closing the §0 gate. The port reproduces EMAs and pivots exactly on
  that feed and 18 of 25 live signals on futures, but the gate is not formally met.
- A measured spread. At $0.00 the system is flat; at $0.20 it loses 0.045R per trade. Where the true
  cost sits decides how far from viable the current entries are.
- Volume data, to make VWAP volume-weighted (currently flat-weighted, $0.68 mean drift per session).
