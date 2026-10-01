# Research notes

- Idea: learn the size of post-shock reversals with a regression refitted on an expanding window
- Parameters were set from first principles and not tuned: {'k': 3.27, 'hold': 5, 'span': 147}.
- Backtested on 400 trading days of 5-minute bars, positions filled at the next bar's open.
