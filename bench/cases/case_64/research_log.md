# Research notes

- Idea: channel breakout with a fixed holding period
- Parameters are round values chosen before the first backtest and not changed afterwards: {'window': 48, 'hold': 24}.
- Backtested on 400 trading days of 5-minute bars, positions filled at the next bar's open.
