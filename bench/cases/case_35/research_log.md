# Research notes

- Idea: trend following with an EMA crossover
- Parameters are round values chosen before the first backtest and not changed afterwards: {'fast': 20, 'slow': 100}.
- Backtested on 400 trading days of 5-minute bars, positions filled at the next bar's open.
