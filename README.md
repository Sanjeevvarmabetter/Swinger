# Global Market Intelligence

A personal daily-briefing and research terminal for **US and Indian markets, gold and commodities, geopolitics, macro
and technology**. Python computes every number from free, delayed data sources; an AI model (Groq, with Gemini as
fallback) only interprets that data, and every link it shows is checked against the sources it was given.

There is no portfolio, trading, journal or broker functionality — this is a research and briefing tool.

## Principles
- **No invented data.** Every price, change, calendar date and headline comes from a named source with a timestamp
  and a freshness label. When a source is missing or unavailable, the page says so instead of filling the gap.
- **Python computes, AI interprets.** The AI receives structured JSON and cites items by id; Python turns ids into
  links and strips any URL that was not supplied.
- **Works without AI.** Every page except the chat is fully usable without an AI key.
- **Mobile first.** Every page is tested at 360–1920 px wide; phones get a bottom navigation bar.

## Pages
| Group | Page | What it does |
|---|---|---|
| — | **Daily Briefing** (home) | Market strip, *Must know* stories, top items per area (US, India, gold, geopolitics, economy, tech, global), X discussions, next-72-hour catalysts, AI-written editions and the facts-only edition |
| Markets | Global Markets · US Markets · Indian Markets · Gold & Commodities | Cross-market tiles, heat maps, risk-appetite checklist, sector/theme leadership, gold driver checks, CFTC positioning |
| Intelligence | Geopolitics · X Intelligence · Live Newsroom · Global Trends Radar · Economic Calendar · News Archive | 16 geopolitical theaters; official X API posts; official YouTube live streams; theme stages; official release schedules and central banks; searchable stored news and past briefings |
| Research | AI Research Chat | Streaming, grounded Q&A with persistent history, verified citations and answer caching |
| System | Settings · System Health | Provider status and connection tests, research parameters, backups; live endpoint checks and feed health |

## Quick start
```bash
uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env          # add GROQ_API_KEY and/or GEMINI_API_KEY (both optional)
.venv/bin/streamlit run app.py
```
Optional keys: `FRED_API_KEY` (release calendar), `FINNHUB_API_KEY` (news, earnings/IPO calendars), `FMP_API_KEY`,
`SEC_USER_AGENT` (EDGAR filings), `X_BEARER_TOKEN` (X Intelligence — paid X API access).

## Scheduled briefings
```bash
.venv/bin/python scripts/intel_scheduler.py --list                 # editions and next run times
.venv/bin/python scripts/intel_scheduler.py --edition global_morning
# crontab: generate due editions every 15 minutes (each edition is made once per day)
*/15 * * * * cd ~/projects/Swinger && .venv/bin/python scripts/intel_scheduler.py >> data/reports/scheduler.log 2>&1
```

## Testing
```bash
.venv/bin/python -m pytest -q                                    # unit/integration tests, no network
uv pip install --python .venv/bin/python -r requirements-dev.txt && .venv/bin/python -m playwright install chromium
.venv/bin/streamlit run app.py --server.port 8599 &               # then, in another shell:
.venv/bin/python tests/e2e/ui_audit.py --out data/qa_screens      # every page × 9 viewports
.venv/bin/python tests/e2e/chat_flow.py --width 390               # LIVE: one real AI request
.venv/bin/python tests/live/ai_eval.py --out data/qa_ai           # LIVE: 9 AI research scenarios
```
See [QA_REPORT.md](QA_REPORT.md) for the latest results.

## Data sources and limits
| Area | Source | Notes |
|---|---|---|
| Prices | Yahoo Finance via `yfinance` | Unofficial, delayed daily bars — never real-time. |
| Macro, US release calendar | FRED (St. Louis Fed) | Each series shows its own observation date. No consensus forecasts (none on current plans; never estimated). |
| News | RSS feeds in `config/news_feeds.json`, Finnhub, SEC EDGAR | Headlines and short summaries only. |
| X posts | Official X API v2 recent search | Disabled until `X_BEARER_TOKEN` is set; daily request budget enforced. |
| Live TV | Official YouTube channels in `config/live_channels.json` | Embeds depend on the broadcaster being live and allowing embedding. |
| AI | Groq (`openai/gpt-oss-120b`, fallbacks) and Google Gemini | Groq free tier ≈ 8,000 tokens/minute; Gemini free tier ≈ 20 requests/day per model. |

## Security
- Secrets live only in `.env` / Streamlit secrets and are never displayed, logged or sent to the browser.
- The Streamlit server binds to `127.0.0.1` by default (`.streamlit/config.toml`).
- `data/` (news archive, briefings, chat history, backups) is git-ignored; one automatic backup is made per day.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design.
