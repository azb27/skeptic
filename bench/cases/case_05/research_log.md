# Research notes

- Idea: fade large bars with a volatility-sized stop and a 1:1 target
- All features use past data only. Walk-forward style: no tuning on the test period.
- Results looked strong across the whole sample, so we did not split it further.
- Parameters: {'k': 2.36, 'span': 98, 'stop_mult': 3.4, 'cooldown': 8}.
