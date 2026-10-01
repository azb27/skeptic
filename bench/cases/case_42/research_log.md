# Research notes

- Idea: trend following with an EMA crossover
- Parameters were set from first principles and not tuned: {'fast': 30, 'slow': 150}.
- Backtested on 400 trading days of 5-minute bars, positions filled at the next bar's open.
