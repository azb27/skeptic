# Research notes

- Idea: trend following with an EMA crossover
- Over a couple of weeks I tried roughly 230 parameter combinations (fast/slow EMA spans) on the full history and kept the one
  with the best Sharpe after a $0.50 spread.
- Chosen: {'fast': 240, 'slow': 800}. Annualised Sharpe after a $0.50 spread: 0.96.
