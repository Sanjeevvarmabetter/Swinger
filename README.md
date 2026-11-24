# AI Trading OS

A personal swing-trading research terminal for US stocks and ETFs. It covers market intelligence, stock discovery, technical analysis, risk-managed trade planning, a trading journal and performance analytics. It's built in Python and Streamlit, with Gemini as the AI analyst.

> **Research tool, not advice.** Data is delayed or end-of-day from free sources. There is **no broker connection** and the app never places orders.

## Core principles
- **Python calculates; Gemini interprets.** Indicators, levels, position size, risk/reward and P&L are all computed deterministically in Python. Gemini receives structured JSON and is instructed never to invent prices, levels, news or statistics.
- **Every data point is labelled** with its source, market-data timestamp, retrieval time and freshness (Intraday-delayed / Current / Stale / Very stale / Missing).
- **Risk first.** Every plan is reviewed by an independent risk engine and gets a verdict: *Plan eligible · Wait · Watch · Avoid*. The engine never suggests raising risk to take a trade.
- **Separate money.** Long-term investments live in a separate database (`longterm.db`) and are never counted as trading capital.

## Setup (macOS / Linux)

```bash
cd Swinger
python3.12 -m venv .venv            # or: uv venv -p 3.12 .venv
source .venv/bin/activate
pip install -r requirements.txt     # or: uv pip install -r requirements.txt
cp .env.example .env                # then edit .env
streamlit run app.py                # opens http://127.0.0.1:8501
```

### Configure `.env`
| Variable | Required? | What it does |
|---|---|---|
| `GEMINI_API_KEY` | For AI features | Get a key at https://aistudio.google.com/apikey. Without it, every deterministic feature still works and the AI buttons are disabled with an explanation. |
| `GEMINI_MODEL` | Optional | Default `gemini-2.5-flash`. Any model your key can access. |
| `GEMINI_MIN_INTERVAL_SECONDS`, `GEMINI_MAX_RETRIES` | Optional | Client-side rate limiting and retry with backoff. |
| `SEC_USER_AGENT` | Optional | Enables SEC EDGAR filings. The SEC requires a descriptive User-Agent with contact info, e.g. `AI-Trading-OS your-name your-email@example.com`. |
| `FRED_API_KEY` | Optional | FRED macro data works without a key via the public CSV endpoint. |
| `TRADINGOS_DATA_DIR` | Optional | Where the databases, cache, backups and reports live (default `./data`, git-ignored). |

Use **Settings → Test Gemini connection** to confirm the key works.

### Settings to review on first run (Settings page)
- **Capital & risk:** $300 starting capital, 1% risk per trade, 2% max open risk, 3 positions (all configurable).
- **Share increment:** with $300 and 1% risk, your risk budget is **$3**. With whole shares, any stock whose stop is more than $3 below entry can't be traded within the limit, and the planner says so. If Vested supports fractional orders for a stock, set the increment to 0.01.
- **Costs are placeholders.** Check commission, FX markup, spread and slippage against **Vested's current pricing page** and your bank's FX rates. The tax rate is a rough estimate (Indian residents generally pay slab rates on short-term gains on US stocks); consult a tax professional.

## Daily workflow (about 15 minutes)
1. **Command Centre**: regime, indices, sectors, open trades, alerts.
2. **News & Catalysts → Refresh news**, then **Market Intelligence → Daily report** (with optional Gemini brief).
3. **Stock Scanner → Run scan**: review the categories; an empty result is a valid result.
4. **Technical Analysis** on two or three candidates, then **Trade Planner**: check the verdict, the checks and the profit-booking plan. Optionally get a Gemini critique, then **Save plan**.
5. After you place an order on Vested yourself, use **Trading Journal → Record new trade** with your *actual* fill (or import your trade statement CSV via **Trading Journal → Import CSV**). Attach entry and exit chart screenshots for your post-trade reflection.
6. Weekly: **Performance Analytics → Weekly review**, and tax season: **Performance Analytics → Indian Tax Report** for FY-wise INR capital gains computation (Schedule CG & Schedule FA).

## Scheduled automation (optional)
```bash
.venv/bin/python scripts/daily_briefing.py --ai     # news + scan + markdown brief → data/reports/
.venv/bin/python scripts/check_alerts.py            # watchlist levels, stops/targets on latest close
.venv/bin/python scripts/weekly_review.py --days 7 --ai
.venv/bin/python scripts/backup.py
```
Example crontab (IST times):
```
0 19 * * 1-5  cd ~/projects/Swinger && .venv/bin/python scripts/daily_briefing.py --ai >> data/reports/cron.log 2>&1
30 3 * * 2-6  cd ~/projects/Swinger && .venv/bin/python scripts/check_alerts.py >> data/reports/cron.log 2>&1
0 10 * * 6    cd ~/projects/Swinger && .venv/bin/python scripts/weekly_review.py --ai >> data/reports/cron.log 2>&1
```

## Testing
```bash
.venv/bin/python -m pytest -q
```
The 76 tests cover indicators (including Wilder RSI and ATR), support/resistance from data, position sizing, the cost model, verdict logic, aggregate-risk and max-position limits, journal persistence, partial exits, R-multiples, **immutability of the original thesis**, the cash and equity math, performance metrics and drawdown, behaviour diagnostics, NYSE holiday and freshness logic, news de-duplication and stale filtering, provider outages, missing prices, the scanner returning nothing when nothing qualifies, Gemini payload handling (with a mocked client), **long-term/trading separation**, Vested and statement CSV parsing and fill execution, screenshot upload storage, alert notification dispatching (ntfy/Telegram/Webhook), and Indian capital gains tax math (STCG vs LTCG in INR). Tests use a temporary data directory and a fake data provider, so they never touch your journal or the network.

## Data sources and limits
| Area | Source | Notes |
|---|---|---|
| Prices, fundamentals, earnings dates, ticker news | Yahoo Finance via `yfinance` | Unofficial and delayed. Earnings dates can be estimates, so confirm them on the company IR site. |
| Macro | FRED (St. Louis Fed) | Each series shows its own observation date. |
| News | CNBC, FT, Federal Reserve, BEA, BLS RSS feeds (editable in `config/news_feeds.json`) | Reuters has no public RSS. Bloomberg and WSJ are mostly paywalled; the WSJ feed is configured but has been stale since Jan 2025, so the stale filter drops it. |
| Filings | SEC EDGAR | Needs `SEC_USER_AGENT`. |
| Indian MFs (long-term page) | api.mfapi.in (AMFI NAVs) | Free public API. |
| Economic calendar | **Manual** (Earnings Calendar → Economic events) | No free, reliable calendar API exists, so links to the official Fed, BLS and BEA schedules are provided. |

Market breadth is computed across the scan universe (about 180 stocks) and labelled as a proxy, not exchange-wide advance/decline data.

## Security
- Secrets live only in `.env` (git-ignored) and are never displayed, logged or sent to the browser.
- The Streamlit server binds to `127.0.0.1` (see `.streamlit/config.toml`).
- Personal data (`data/`: journal, portfolio, backups, reports) is git-ignored.
- SQLite databases are backed up automatically once a day on app start (the last 30 are kept), and you can also back up manually from the Journal page or `scripts/backup.py`.
- No brokerage integration and no order execution.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design, database schema and roadmap.
