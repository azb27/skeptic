# Research notes

- Idea: trend following with an EMA crossover
- We searched a parameter grid (listed in params.json, 273 combinations) and kept the best by Sharpe after costs.
- Chosen: {'fast': 420, 'slow': 1000}. Annualised Sharpe after a $0.50 spread: 1.09.
