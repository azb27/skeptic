# Research notes

- Idea: trend following with an EMA crossover
- All features use past data only. Walk-forward style: no tuning on the test period.
- Results looked strong across the whole sample, so we did not split it further.
- Parameters: {'fast': 30, 'slow': 100}.
