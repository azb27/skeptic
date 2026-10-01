# Research notes

- Idea: fade large bars with a volatility-sized stop and a 1:1 target
- Parameters are round values chosen before the first backtest and not changed afterwards: {'k': 2.75, 'span': 80, 'stop_mult': 3.5, 'cooldown': 4}.
- Backtested on 400 trading days of 5-minute bars, positions filled at the next bar's open.
