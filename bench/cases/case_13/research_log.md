# Research notes

- Idea: fade bars that move far more than recent volatility
- Parameters were set from first principles and not tuned: {'k': 2.31, 'span': 140, 'hold': 8}.
- Backtested on 400 trading days of 5-minute bars, positions filled at the next bar's open.
