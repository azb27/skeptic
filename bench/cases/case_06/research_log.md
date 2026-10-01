# Research notes

- Idea: large moves partially retrace; hold the counter-trade for a few bars
- Parameters were set from first principles and not tuned: {'k': 2.76, 'span': 96, 'hold': 5}.
- Backtested on 400 trading days of 5-minute bars, positions filled at the next bar's open.
