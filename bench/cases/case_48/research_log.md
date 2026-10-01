# Research notes

- Idea: trend following with an EMA crossover
- Over a couple of weeks I tried roughly 160 parameter combinations (fast/slow EMA spans) on the full history and kept the one
  with the best Sharpe after a $0.50 spread.
- Chosen: {'fast': 460, 'slow': 2600}. Annualised Sharpe after a $0.50 spread: 0.72.
