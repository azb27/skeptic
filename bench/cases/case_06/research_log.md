# Research notes

- Idea: trend following with an EMA crossover
- We searched a parameter grid (listed in params.json, 279 combinations) and kept the best by Sharpe after costs.
- Chosen: {'fast': 240, 'slow': 1400}. Annualised Sharpe after a $0.50 spread: 1.21.
