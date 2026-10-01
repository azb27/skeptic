# Research notes

- Idea: gold has recurring intraday seasonality; hold a position through the best window of UTC hours
- We searched a parameter grid (listed in params.json, 204 combinations) and kept the best by Sharpe after costs.
- Chosen: {'start': 10, 'end': 14, 'side': -1}. Annualised Sharpe after a $0.50 spread: 1.31.
