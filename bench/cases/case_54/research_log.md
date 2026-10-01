# Research notes

- Idea: learn the size of post-shock reversals with a regression refitted on an expanding window
- Parameters are round values chosen before the first backtest and not changed afterwards: {'k': 3.0, 'hold': 4, 'span': 120}.
- Backtested on 400 trading days of 5-minute bars, positions filled at the next bar's open.
