# Architecture

```
┌──────────────────────────── Streamlit UI (app.py + views/*) ────────────────────────────┐
│ Command Centre · Market Intel · Scanner · Technical · Gemini Analyst · Trade Planner ·   │
│ News · Earnings · Watchlist · Journal · Performance · Long-term · Settings              │
└──────────────┬──────────────────────────────────────────────────────┬──────────────────┘
               │ tradingos/ui (components, charts, cached state)      │
┌──────────────▼───────────── tradingos/services.py (orchestration) ──▼──────────────────┐
│ stock_context · market_context · build_trade_plan · fundamentals · briefing            │
└──┬────────────┬──────────────┬──────────────┬───────────────┬──────────────┬───────────┘
   │analysis/   │risk/engine   │journal/      │performance/   │ai/gemini     │longterm
   │indicators  │(pure, tested)│service       │metrics,       │(interprets   │(separate DB)
   │technical   │              │(fills → P&L) │backtest       │ JSON only)   │
   │market      │              │              │               │              │
   │scanner     │              │              │               │              │
┌──▼────────────▼──────────────▼──────────────▼───────────────▼──────────────▼───────────┐
│ data/ providers (MarketDataProvider → YFinanceProvider) · macro (FRED) · news (RSS,      │
│ Yahoo, EDGAR) · base (DataResult + freshness + NYSE calendar) · cache (disk TTL)         │
└──┬───────────────────────────────────────────────────────────────────────────────────────┘
   │ db/ SQLAlchemy → trading.db  |  longterm.db  (physically separate)
```

## Key design decisions
| Decision | Reason |
|---|---|
| `DataResult` wrapper on every provider call | The UI can always show source, as-of date, retrieval time, freshness and missing symbols. A batch's as-of date is the most common last-bar date, and lagging symbols are listed. |
| Provider abstraction (`MarketDataProvider`) | Polygon, FMP or Finnhub can replace yfinance by implementing 5 methods and registering in `get_market_provider()`. |
| Deterministic regime, scanner score and verdicts | Transparent rule points with breakdowns. Nothing is presented as a probability. |
| Risk engine is pure functions | It is exhaustively unit-tested, and the UI, scripts and Gemini payloads all use the same numbers. |
| P&L derived from fills | Supports partial exits, fees and FX per fill, and correct R-multiples. Equity = contributed − transfer FX + realized ± open marks. |
| ORM `before_flush` guard | The original thesis, plan levels and risk % on a trade cannot be modified after creation. |
| Separate `longterm.db` | Long-term holdings cannot be counted in trading equity even by accident. |
| Gemini output stored in `ai_reports` with its input JSON | Every AI statement can be audited against the data it was given. |

## Database schema — `trading.db`
| Table | Purpose / key columns |
|---|---|
| `settings` | `key`, `value_json` (TradingSettings dataclass) |
| `capital_flows` | `flow_date`, `kind` DEPOSIT/WITHDRAWAL, `amount_usd`, `inr_amount`, `fx_rate`, `fx_cost_usd`, `notes` |
| `trade_plans` | `ticker`, `setup`, `thesis`, `entry_trigger`, `entry`, `stop`, `target1/2`, `shares`, `risk_usd`, `reward_risk`, `verdict`, `checks_json`, `data_as_of`, `ai_review`, `status` |
| `trades` | **Immutable:** `entry_thesis`, `planned_entry`, `initial_stop`, `initial_target(2)`, `planned_risk_pct`, `equity_at_entry`, `ticker`, `setup`. **Mutable:** `status`, `current_stop`, `closed_at`, `exit_reason`, `lessons`, `chart_ref`, `mistake_tags` |
| `fills` | `trade_id`, `side` BUY/SELL, `filled_at`, `qty`, `price`, `commission`, `fx_cost`, `other_costs`, `note` |
| `stop_changes` | `trade_id`, `changed_at`, `old_stop`, `new_stop`, `reason` (widened stops are flagged) |
| `watchlist` | `ticker`, `notes`, `tags`, `alert_above`, `alert_below` |
| `alerts` | `ticker`, `message`, `acknowledged` |
| `news_items` | `dedupe_key` (unique), `headline`, `summary`, `source`, `url`, `published_at`, `tickers`, `category`, `sector`, `sentiment`, `impact`, `info_type` |
| `econ_events` | `event_date`, `title`, `category`, `importance`, `source_url` |
| `scan_runs` | `run_at`, `data_as_of`, `params_json`, `results_json` |
| `ai_reports` | `kind`, `subject`, `model`, `input_json`, `output_text` |

`longterm.db` has one table, `lt_holdings`: `asset_class`, `symbol`, `name`, `quantity`, `avg_cost`, `currency`, `price_source` (yfinance/mfapi/manual), `manual_price`, `manual_price_date`.

## Calculation reference
- **Risk budget** = equity × risk %. **Risk/share** = |entry − stop|. **Shares** = floor(budget / risk-per-share) to the share increment, capped by cash (no leverage). If one increment's risk exceeds the budget, the trade is **unsuitable**.
- **Planned loss (net)** = shares × risk/share + estimated round-trip costs at the stop. Aggregate open risk = Σ max(0, (avg entry − current stop) × open qty).
- **R-multiple** = net realized P&L ÷ (first fill − initial stop) × bought qty.
- **Profit factor** = gross wins ÷ gross losses. **Expectancy** = mean net P&L per trade (and mean R).
- **Drawdown** is measured on *performance equity* (starting capital + cumulative realized P&L), so deposits don't mask losses.
- **RSI/ATR**: Wilder smoothing. **Support/resistance**: swing pivots (±5 bars) clustered within max(0.5 ATR, 1.5%), plus the period high.

## Roadmap
**Done (v0.2):**
- Phases 1–6 as described in the README.
- **Journal CSV Statement Importer:** Direct import of Vested activity exports, DriveWealth confirmations, or generic CSV trade statements with preview, validation, and automated fill execution.
- **Indian Capital Gains Tax Helper:** FY-wise realized capital gains computed in INR (Schedule CG & Schedule FA format), distinguishing STCG (≤ 24m, slab rate) and LTCG (> 24m) using historical USD/INR rates.
- **Screenshot Storage & Chart Snapshots:** Upload and persistence of entry and exit chart images directly attached to journal reflections.
- **Push Alert Notifications:** Instant alert dispatching via ntfy.sh (free mobile/browser push), Telegram Bot API, and custom Webhooks from `scripts/check_alerts.py` and UI.

**Next candidates**
1. **Data:** a paid provider adapter (Polygon/FMP/Finnhub) for real-time quotes, reliable earnings calendars and an economic calendar. Check pricing and terms before integrating.
2. **Universe:** load full index constituents dynamically, with survivorship-aware history for backtests.
3. **Backtesting:** portfolio-level backtests across the universe with regime filters (vectorbt), walk-forward validation and cost sensitivity.
4. **AI:** Gemini structured output (JSON schema) for verdict and critique fields; Gemini news classification as an optional second pass over the keyword heuristic.
5. **Options:** intentionally out of scope for v1.

## Global Market Intelligence layer (Stage 1, 2026-11-24)

```
views/daily_briefing · global_markets · us_markets · india_markets · gold_commodities · system_health
        │  tradingos/ui/intel_ui.py (st.cache_data wrappers, tiles, heatmaps, story cards)
tradingos/intel/
  instruments.py  registry of ~110 verified Yahoo symbols + exchange calendars + explicit UNAVAILABLE list
  freshness.py    per-exchange bar freshness (NYSE holidays; other exchanges weekday-only → lag flagged as
                  "possible holiday or provider lag", never silently "current")
  markets.py      one batched snapshot (1D/1W/1M/3M/YTD/1Y, 200DMA, freshness) + risk-appetite checklist
  gold.py         driver checks vs DXY / DFII10 / T10YIE, 60d correlations, CFTC COT positioning, INR/10g
  calendars.py    FRED release dates (official), Finnhub earnings/IPO, FMP earnings fallback, manual events
  news_rank.py    word-boundary keyword topics, near-duplicate clustering, transparent score → tiers
                  (MUST KNOW / IMPORTANT / INTERESTING / IGNORE FOR NOW)
  briefing.py     editions + DST-aware schedule, payload → facts-only markdown → Gemini editor → `briefings` table
  health.py       live per-endpoint plan checks (OK / NOT IN PLAN / NOT CONFIGURED / ERROR), feed status
scripts/intel_scheduler.py  idempotent cron entry point (*/15) — generates due editions
```

Plan permissions verified 2026-11-24: Finnhub economic calendar 403; FMP economic calendar, IPO calendar and
general news 402. Hence no macro forecasts/consensus anywhere. DB migration: `db.session.add_missing_columns`
adds new nullable columns (e.g. `news_items.region`) to existing SQLite files; nothing is dropped.

## Stage 2 (2026-11-24): Geopolitics · News Intelligence · Economic Calendar · Trends Radar

```
tradingos/intel/entities.py     gazetteer entity extraction (countries, institutions) — explainable, no ML
tradingos/intel/geopolitics.py  16 theaters: EVIDENCE (matched stories, corroboration, official vs speculative,
                                attention, market reaction) kept separate from static FRAMEWORK (channels, exposures,
                                what to monitor). Event cards answer the 11 standard questions.
tradingos/intel/trends.py       30 themes from config/themes.json → equal-weight baskets → RS 1M/3M/6M, 200DMA,
                                RSI, breadth, news attention → rule ladder (Crowded › Weakening › Gaining momentum ›
                                Established › Emerging › Out of favour › No clear trend)
tradingos/intel/calendars.py    + FOMC dates parsed from federalreserve.gov, FRED readings per release
                                (actual only if FRED updated on/after the release date and no later release
                                superseded it), central-bank tracker (FRED policy rates + official RSS comms)
tradingos/intel/news_rank.py    + threads() for developing stories
views/geopolitics · trends_radar · economic_calendar · news (rewritten as News Intelligence)
```

Attention ratios (7d vs prior 28d) are withheld until ~35 days of news have been collected AND the baseline has
≥4 stories — RSS only exposes a few days, so early ratios would be meaningless. News is now retained 35 days.
