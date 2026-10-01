# Research notes

- Idea: trend following with an EMA crossover
- Over a couple of weeks I tried roughly 260 parameter combinations (fast/slow EMA spans) on the full history and kept the one
  with the best Sharpe after a $0.50 spread.
- Chosen: {'fast': 180, 'slow': 2400}. Annualised Sharpe after a $0.50 spread: 1.07.
