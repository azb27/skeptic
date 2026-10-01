# Research notes

- Idea: trend following with an EMA crossover
- We searched a parameter grid (listed in params.json, 272 combinations) and kept the best by Sharpe after costs.
- Chosen: {'fast': 260, 'slow': 600}. Annualised Sharpe after a $0.50 spread: 0.92.
