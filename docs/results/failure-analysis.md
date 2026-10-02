# Bench failure analysis

Every number here comes from `docs/results/bench.md` (`python -m evals.report`) or from the per-case records in `runs/evals/<config>/results.jsonl` that it reads. One run per configuration, 90 cases, built 2 Oct 2026. Hand-written; the tables it cites are not.

## What the bench says, in four lines

1. **On verdicts alone, the agent does not beat fixed rules by a provable margin.** Sonnet 97% vs rules-only 94%, McNemar p = 0.73. The truncation probe and the backtest already catch most flaws, as the spec predicted.
2. **The agent's value is the reason and the location.** Right reason: 88% vs 49%. Leak line found within ±3: 89% vs 0%. On the 13 leaks the probe cannot see, Sonnet rejected all 13 and pointed at the line in 10; the rules rejected 9 of them, all for the wrong reason (no edge on a null market).
3. **The checks are what let an LLM say yes.** Sonnet reading code with no checks rejected 25 of 30 real edges (p = 1.6e-6 against the full system). Without numbers, a skeptical model rejects nearly everything, so its 100% on leaks means little.
4. **Haiku is close on verdicts (96%) but fails in a worse way.** Its false rejects invent leaks that aren't there; Sonnet's cite a real discrepancy and over-weight it.

## Every Sonnet error: one pattern, three cases

All three are real edges rejected with class `process` (case_28, case_42, case_74). In each the research log says the parameters were "round values chosen before the first backtest and not changed", while the strategy class has *different* default arguments (for example `threshold=2.5, horizon=6` in code, `k=2.25, hold=8` in `params.json`). Sonnet read the mismatch as evidence of undisclosed tuning, noted that no trial count was recorded, and rejected even though every check passed.

- **Is it wrong?** By the bench's ground truth, yes: the bench draws `params.json` independently of the class defaults, and no search happened. In real code, defaults that differ from the chosen values are common and prove nothing.
- **Is it unreasonable?** No. An undisclosed search is exactly what the multiple-testing group plants, and a reviewer who asks "why do these differ?" is doing the job. It is over-skepticism, not hallucination: every cited line exists and says what Sonnet says it does.
- **What I did about it:** nothing to the bench or the scorer. Changing either after seeing which cases fail would tune the benchmark to the model, which is the flaw Skeptic exists to catch. The cost is reported as it stands: 3 of 30 real edges falsely rejected (10%).
- **The fix belongs in the product, not the bench:** a `process` concern with every check passing should come back as SURVIVES CHECKS with a caveat, not as REJECT. That is a prompt or schema change, and it has to be measured on a fresh run, not this one.

## Where each configuration fails

| Configuration | Wrong verdicts | Pattern |
|---|---:|---|
| Rules only | 5 | Four probe-blind leaks on real-edge markets (unpurged labels, fitting on the full sample) pass every numeric check, so a rule has nothing to reject on. The fifth (case_89) is best-of-~230 selection whose trial count is only in the prose of the research log. Sonnet read it there, ran `multiple_test` with n = 230 and got DSR 0.40. |
| Sonnet: code + checks | 3 | False rejects on `process`, above. No missed flaws. |
| Haiku: code + checks | 4 | Three false rejects claiming a leak the probe had just cleared: on case_47 it misreads the contract (positions are decided at the bar's close, so using that close is legal); on case_28 and case_58 it calls a correctly right-labelled hourly resample a look-ahead. One probe-blind leak (case_69) missed. |
| Sonnet: checks only | 8 | The rules' five misses (it can't read the code that holds the leak), plus three false rejects. All three cite `multiple_test` returning INFO because no trial count is recorded; the check's own caveat ("an unrecorded search is a caveat, not a pass") was read as a reason to reject. |
| Sonnet: code only | 26 | 25 false rejects, 21 of them `process` and two `no_edge` asserted without a single number, and one null-market case passed. |

## Localisation misses (Sonnet, 4 of 35 leaks)

- **case_15:** the evidence list cites the planted line (`strategy.py:22-23`, training labels without an embargo), but the structured `line` field names the label construction five lines earlier. The scorer reads only the structured field, so this counts as a miss. Lenient scoring would make it 32/35; the headline stays strict.
- **case_40, case_52:** unpurged labels on a null market. The backtest already rejects, and Sonnet stopped there (`no_edge` on case_40; the right class but no line on case_52). Right verdict, no location.
- **case_50:** selection on the full sample, flagged by the probe; the right class, but the verdict gives no line.

Unpurged labels are the hardest class to locate for both models: the bug is an *absence* (no gap between training labels and the test start), so there is no single offending expression to point at.

## What this changes

- The README leads with **right reason and localisation**, not verdict accuracy, because that is where the difference is statistically real.
- The code-only ablation is the strongest single result: it shows why the LLM must never produce the statistic.
- Next measured change: the `process`-with-passing-checks rule above, on a fresh run of all 90 cases, reported next to this one.
