# Research notes

- Idea: fade bars that move far more than recent volatility
- Parameters are round values chosen before the first backtest and not changed afterwards: {'k': 2.5, 'span': 120, 'hold': 6}.
- Backtested on 400 trading days of 5-minute bars, positions filled at the next bar's open.
