# Research notes

- Idea: fade large bars with a volatility-sized stop and a 1:1 target
- Parameters were set from first principles and not tuned: {'k': 2.64, 'span': 116, 'stop_mult': 3.19, 'cooldown': 6}.
- Backtested on 400 trading days of 5-minute bars, positions filled at the next bar's open.
