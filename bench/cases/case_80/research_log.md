# Research notes

- Idea: gold has recurring intraday seasonality; hold a position through the best window of UTC hours
- We searched a parameter grid (listed in params.json, 227 combinations) and kept the best by Sharpe after costs.
- Chosen: {'start': 1, 'end': 9, 'side': -1}. Annualised Sharpe after a $0.50 spread: 1.1.
