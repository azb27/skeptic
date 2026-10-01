# Research notes

- Idea: fade bars that move far more than recent volatility
- Parameters were set from first principles and not tuned: {'k': 2.61, 'span': 115, 'hold': 6}.
- Backtested on 400 trading days of 5-minute bars, positions filled at the next bar's open.
