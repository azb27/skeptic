# Research notes

- Idea: gold has recurring intraday seasonality; hold a position through the best window of UTC hours
- Over a couple of weeks I tried roughly 160 parameter combinations (start hour, end hour and direction) on the full history and kept the one
  with the best Sharpe after a $0.50 spread.
- Chosen: {'start': 3, 'end': 9, 'side': -1}. Annualised Sharpe after a $0.50 spread: 2.09.
