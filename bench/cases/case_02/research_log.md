# Research notes

- Idea: trend following with an EMA crossover
- We searched a parameter grid (listed in params.json, 278 combinations) and kept the best by Sharpe after costs.
- Chosen: {'fast': 80, 'slow': 4400}. Annualised Sharpe after a $0.50 spread: 1.01.
