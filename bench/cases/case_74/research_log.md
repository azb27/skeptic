# Research notes

- Idea: large moves partially retrace; hold the counter-trade for a few bars
- Parameters are round values chosen before the first backtest and not changed afterwards: {'k': 2.25, 'span': 100, 'hold': 8}.
- Backtested on 400 trading days of 5-minute bars, positions filled at the next bar's open.
