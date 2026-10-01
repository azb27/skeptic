# Corrections to the bench

Flaws in the bench itself, found while running it. Each one is fixed at the source and the affected runs are re-done.

| # | Found by | Flaw | Effect | Fix |
|---|---|---|---|---|
| 1 | The Sonnet auditor, in the 24-case pilot of the first bench build | Survivor cases' notes said parameters were "set from first principles and not tuned", but the values were drawn at random to two decimals (k=3.27, span=106). Those look like the output of a parameter search. | The auditor rejected 4 of 4 such survivors as a process flaw, which is a reasonable reading of the evidence. The bench, not the auditor, was wrong. | Parameters are now round values from short lists (k ∈ {2.25, 2.5, 2.75}, …), and the notes say they were chosen before the first backtest. The bench was rebuilt and every run repeated. |
| 2 | Running `future_blind` on the Gold Sniper harness (case study) | The probe counted a signal that vanished on the final bar of truncated data as look-ahead. The harness reports completed trades only, so a trade still open when the data ends is dropped: that is censoring, not a leak. | False REJECT on the case study (4 mismatches, each on the cut bar itself). The bench was unaffected, since its bracket strategies report every signal. | For bracket strategies, a signal that is only *missing* within one trade life of the cut is ignored. A signal that appears, flips or moves still counts. Tests cover both directions. The probe then passes the harness at all 30 cut points. |
