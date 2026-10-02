# Research log: shock fade

- Idea: after an unusually large 5-minute move, price partly reverts over the next half hour.
- Parameters fixed before the first backtest: k = 3.0 (a move three times the recent average), span = 100 bars, hold = 6 bars.
- One configuration was run. No parameter was changed after seeing results.
- Data: a seeded synthetic market (this folder is a demo of Skeptic, not a real strategy).
