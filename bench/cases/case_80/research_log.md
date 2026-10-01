# Research notes

- Idea: fade large bars with a volatility-sized stop and a 1:1 target
- Parameters were set from first principles and not tuned: {'k': 2.74, 'span': 127, 'stop_mult': 2.6, 'cooldown': 7}.
- Backtested on 400 trading days of 5-minute bars, positions filled at the next bar's open.
