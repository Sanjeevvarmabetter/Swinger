# Architecture

```
┌──────────────────────────────── Streamlit UI (app.py + views/*) ───────────────────────────────┐
│ Daily Briefing · Global/US/Indian Markets · Gold & Commodities · Geopolitics · X Intelligence ·  │
│ Live Newsroom · Trends Radar · Economic Calendar · News Archive · AI Research Chat · Settings    │
│ mobile: bottom navigation (≤767px) + sidebar menu; design tokens in tradingos/ui/components.CSS  │
└───────────────┬──────────────────────────────────────────────────────────────┬─────────────────┘
                │ tradingos/ui (components, intel_ui renderers, charts, cached state)
┌───────────────▼──────────── tradingos/intel (orchestration) ─────────────────▼─────────────────┐
│ markets · gold · geopolitics · trends · calendars · news_rank · briefing (payload, editions,     │
│ archive) · research (chat context + budget) · chat_store · xintel (X API) · health              │
└──┬──────────────────────┬───────────────────────────┬────────────────────────┬─────────────────┘
   │ analysis/             │ services.py               │ ai/gemini.py           │ ai/formatting.py
   │ indicators, market,   │ stock_context,            │ Groq + Gemini clients, │ answer clean-up: tables,
   │ technical snapshot    │ market_context,           │ streaming, quota-aware │ JSON, unicode, id→link
   │                       │ fundamentals              │ fallback, size routing │ citations, link guard
┌──▼───────────────────────▼───────────────────────────▼────────────────────────▼─────────────────┐
│ data/ providers (yfinance) · macro (FRED) · news (RSS, Finnhub, EDGAR) · base (DataResult +      │
│ freshness + exchange calendars) · cache (disk TTL)                                               │
└──┬────────────────────────────────────────────────────────────────────────────────────────────────┘
   │ db/ SQLAlchemy → data/trading.db  (news_items, briefings, ai_reports, econ_events, chat_messages, settings)
```

## AI pipeline
1. **Context selection** (`intel/research.py`): detect topics in the question (US, India, gold, geopolitics, tech,
   macro, global), pick only the relevant market tables, rank stored news by relevance, add company data when a
   ticker or company name is mentioned. Each news/official item gets an id (`N3`, `C1`, `G2`, `B1`).
2. **Budget** (`fit_context`): trims the context to ~9k characters (Groq free tier: 8k tokens/minute), most
   expendable first; the source list is filtered to what the model actually received.
3. **Generation** (`ai/gemini.py`): streaming via Groq SSE (UTF-8 decoded explicitly) or Gemini
   `generate_content_stream`. Provider fallback happens only before the first token; a mid-answer failure is shown
   as an error, never silently replaced. One-shot analyses with large payloads go to Gemini first and Groq gets a
   structurally shrunk payload (`shrink_json`, never cut mid-JSON).
4. **Clean-up** (`ai/formatting.py`): strip reasoning tags, unwrap whole-answer code fences, render raw JSON as
   bullets, repair tables, de-duplicate repeated paragraphs, normalise unicode minus/spaces, turn id markers into
   links, remove any link not in the supplied data, colour signed % moves.
5. **Persistence**: chat messages in `chat_messages` (conversation id in the URL so refresh keeps it), every call in
   `ai_reports`, identical question + identical data reuses the cached answer for 30 minutes.

## Key design decisions
| Decision | Reason |
|---|---|
| `DataResult` wrapper on every provider call | The UI always shows source, as-of date, retrieval time, freshness and missing symbols. |
| Deterministic news ranking and tiers | Must Know / Important / Interesting are rule-based and explainable; AI may only re-tier with a stated reason. |
| Citations by id, links built in Python | Models cannot fabricate a working source link. |
| X only through the official API with a request budget | Pay-per-use pricing; nothing scraped, nothing invented. |
| Removed trading tables are not dropped | Code no longer creates them; existing files keep any old rows until the user drops them (see QA_REPORT.md). |
