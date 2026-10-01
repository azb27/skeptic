# Research notes

- Idea: large moves partially retrace; hold the counter-trade for a few bars
- Parameters were set from first principles and not tuned: {'k': 2.48, 'span': 133, 'hold': 4}.
- Backtested on 400 trading days of 5-minute bars, positions filled at the next bar's open.
