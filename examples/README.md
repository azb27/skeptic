# Example strategy folders

Two folders you can audit without downloading anything (both use a seeded synthetic market):

| Folder | What it is |
|---|---|
| `fade_clean/` | Fades large moves, with volatility measured on past bars only. |
| `fade_leaky/` | The same idea, but "typical move" comes from a window centred on the bar, so it uses the next 50 bars. |

```bash
skeptic audit examples/fade_leaky          # the API auditor (needs ANTHROPIC_API_KEY)
skeptic check examples/fade_leaky future_blind   # one deterministic check, no API
```
or, in Claude Code inside this repo: `/skeptic examples/fade_leaky`.

Your own folder needs `strategy.py` and a `params.json` with a `data` entry; see `src/skeptic/folder.py`.
