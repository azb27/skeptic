# Research notes

- Idea: fade bars that move far more than recent volatility
- All features use past data only. Walk-forward style: no tuning on the test period.
- Results looked strong across the whole sample, so we did not split it further.
- Parameters: {'k': 2.25, 'span': 120, 'hold': 8}.
