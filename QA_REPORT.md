# QA Report — Global Market Intelligence

**Date:** 25 Nov 2026 (IST) · **Stack:** Python 3.12 · Streamlit 1.67 · SQLite · Groq + Google Gemini · Playwright (Chromium)

All results below come from runs made during this QA pass. Anything that wasn't tested is listed under
[Remaining limitations](#10-remaining-limitations).

| Check | Result |
|---|---|
| Unit and integration tests (`pytest`) | **123 passed**, 0 failed |
| Browser audit, 14 pages × 9 viewports (360–1920 px) | **126 / 126 clean**: no Python exceptions, no console errors, no failed requests, no horizontal page overflow |
| Live AI scenarios (real Groq calls) | **9 / 9 passed** the automated checks, and the answers were reviewed by hand |
| Live chat browser flow at 360, 390 and 1440 px | **Passed** at all three widths |
| Static analysis (`pyflakes`) | Clean, apart from the intentional `_bootstrap` imports in scripts |
| Dependency vulnerabilities (`pip-audit`, every installed package) | **No known vulnerabilities** |

> The app is Streamlit (Python). There is no separate JavaScript frontend or bundle to build. Running the app and
> the browser audit is the equivalent of a "production build" check.

---

## 1. Features audited

| Page | What was checked |
|---|---|
| Daily Briefing (home) | Market strip, risk checklist, the *Today* tab (Must Know, per-area sections, X, next 72 h catalysts), AI briefing tab (generation, archive picker, stale-issue warning, link verification), facts-only edition, schedule tab. One AI edition was generated end-to-end (52 s, Gemini fallback chain including a 503 retry). |
| Global / US / Indian Markets, Gold & Commodities | Tiles, heat maps, charts, tables, AI analyst panels. The Gold panel was run live: a 16.8k-character payload went to Gemini, and the output is structured and labelled. |
| Geopolitics, Global Trends Radar, Economic Calendar | Page loads, tabs, filters, AI panels (payload-verified links) |
| X Intelligence (new) | Not-configured state, configured path with mocked API (parsing, caching, daily budget, 401/402/429 handling) |
| Live Newsroom (new) | 12 official channels with IDs verified against youtube.com. Region filter, channel picker, 16:9 responsive embed. The Bloomberg live stream rendered in the test. Fallback links are provided. |
| News Archive (was News Intelligence) | Search, window (1–365 days), filters, cards/table, "show more", past-briefings archive, story threads, entities, sources, AI synthesis |
| AI Research Chat (new, replaces AI Analyst) | Streaming, formatting, citations, history persistence across reload, history popover, new chat, answer cache, error states, no-AI state |
| Settings | Provider status and connection tests, research parameters (validated), cache clear, backup |
| System Health | Endpoint checks (now including Groq and X), feed status |
| Scripts | `intel_scheduler.py --help/--edition`, `backup.py` |

## 2. Features removed

Removed: **long-term portfolio, trading desk, trade planner, trading journal, performance analytics, trading-specific
AI analyst, scanner, technical-analysis trade levels, watchlist and price alerts, Indian tax report, and every
P&L, position and risk-engine feature.**

- **Pages (10):** `command_centre`, `trade_planner`, `journal`, `performance`, `longterm`, `scanner`, `technical`,
  `watchlist`, `earnings`, `market_intel`. `ai_analyst` was replaced by `ai_research`.
- **Packages and modules:** `tradingos/journal/*`, `performance/*`, `risk/*`, `tax/*`, `longterm.py`, `watchlist.py`,
  `alerts.py`, `briefing.py` (legacy), `analysis/scanner.py`, and the trade-level helpers in
  `analysis/technical.py` and `ui/charts.py`.
- **Scripts:** `check_alerts.py`, `weekly_review.py`, `daily_briefing.py` (legacy). `intel_scheduler.py` replaces it.
- **Models:** `CapitalFlow`, `WatchlistItem`, `TradePlan`, `Trade`, `Fill`, `StopChange`, `ScanRun`, `Alert`,
  `LongTermHolding`, the immutability guard, and the `longterm.db` engine.
- **Settings:** the capital, risk, cost, tax, scanner and alert fields. Old saved settings still load because unknown
  keys are ignored (covered by a test).
- **Tests:** journal, performance, risk and importer/tax/alerts. The remaining tests were updated.
- **AI prompts:** the swing-trading system prompt and trade-plan, risk, weekly-review and stock tasks.
- **Text:** "Stage 3" placeholders, swing-trading guidance in the market-regime text, and "AI Trading OS" branding.

Shared code was kept: indicators, the market regime and breadth logic, the technical snapshot used for company
research, `services.stock_context` and `fundamentals`, news, macro, calendars, and all intel modules.

**Database (non-destructive):** the code no longer creates or uses the trading tables, but **existing tables in
`data/trading.db` were not dropped**, and `data/longterm.db` was not deleted. At audit time those tables held
0 rows, except `scan_runs` with 3 rows. If you want them gone, back up first and then run:
```bash
.venv/bin/python scripts/backup.py
sqlite3 data/trading.db "DROP TABLE IF EXISTS fills; DROP TABLE IF EXISTS stop_changes; DROP TABLE IF EXISTS trades;
  DROP TABLE IF EXISTS trade_plans; DROP TABLE IF EXISTS capital_flows; DROP TABLE IF EXISTS watchlist;
  DROP TABLE IF EXISTS scan_runs; DROP TABLE IF EXISTS alerts; VACUUM;"
rm data/longterm.db
```

## 3. Bugs discovered

| # | Bug | How it was found |
|---|---|---|
| 1 | **Groq streaming text decoded as ISO-8859-1.** Every `—`, `₹`, `’` appeared as mojibake (`â€”`). | Live AI eval output |
| 2 | **Every chat request exceeded Groq's free-tier 8,000 tokens/min (HTTP 413)** and silently fell back to Gemini's last-resort model. | Live AI eval, confirmed by probing the API |
| 3 | AI briefings and AI panels only ran when **Gemini** was configured, so a Groq-only setup failed | Code review |
| 4 | **No clickable citations.** gpt-oss writes `【news[1]】` or `(N2)` markers instead of Markdown links. | Live AI eval |
| 5 | The gold driver table's 1-month change was reported by the AI as a **daily** move | Reviewing live answers |
| 6 | De-duplicating sources by URL dropped geopolitics citation IDs, so valid citations were discarded | Reviewing live answers |
| 7 | **Chat history lost on page refresh**, because a new Streamlit session meant a new conversation | Chat browser test design |
| 8 | Phones: the sidebar opened over the content by default | Baseline screenshot (375 px) |
| 9 | Phones: 10 market tiles stacked one per row, about 1,100 px before any news | Baseline screenshot |
| 10 | The old AI Analyst page overflowed horizontally by 24 px at 375 px | Baseline audit |
| 11 | Heat-map titles overlapped the Plotly toolbar and column labels on phones | Screenshot review |
| 12 | A provider badge was clipped at 768 px (Settings) | Screenshot review |
| 13 | Unicode minus, en dash and narrow no-break spaces stopped the green/red colouring of moves and showed `7 196.87` | Mobile chat screenshot |
| 14 | Feed URLs were rendered as `href` with no scheme check, so a `javascript:` link was possible | Security review |
| 15 | Old payload handling **cut JSON mid-string** at 120k characters before sending it to the AI | Code review |
| 16 | Market-regime text gave trading advice ("Cash is a position") | Code review |
| 17 | The chat input had a double focus ring | Screenshot review |
| 18 | Groq 413/429 errors showed raw HTTP bodies to users | Live runs |

## 4. Bugs fixed

All 18 are fixed, with regression tests where the bug can be tested:

| # | Fix |
|---|---|
| 1 | `resp.encoding = "utf-8"` before reading the stream. Test: `test_groq_stream_decodes_utf8`. |
| 2 | `research.fit_context()` trims the chat context to about 9k characters (most expendable data first). Older chat turns are shortened. Test: `test_fit_context_*`. |
| 3 | Uses `ai_configured`. Large one-shot payloads go to Gemini first; Groq gets a payload shrunk with `shrink_json` (halves ranked lists and never breaks the JSON). Test: `test_large_payload_prefers_gemini_and_groq_gets_shrunk`. |
| 4 | Every context item has an ID (`N3`, `C1`, `G2`, `B1`). The model cites IDs, and Python turns `[N3]`, `【N3】`, `(N3)`, `(Source, N3)` and bare `N3` into links. Unknown IDs are removed; `G7` and `G20` are never touched. |
| 5 | The column is now labelled "Change over last 1 month". Re-checked live: the answer says "over the past month". |
| 6 | Duplicate IDs are kept as aliases. On the same raw answer, linked citations went from 2 to 7. |
| 7 | Messages are stored in `chat_messages`, and the conversation ID is in the URL (`?c=…`). Verified with a browser reload. |
| 8 | `initial_sidebar_state="auto"`, plus a bottom navigation bar on phones (Briefing, Markets, News, Calendar, AI Chat) with an active-page highlight. |
| 9 | Tiles are a CSS grid (two per row on phones, auto-fill on larger screens) with a compact mobile style. |
| 10 | Page replaced. Overflow is 0 at every width. |
| 11 | Toolbar hidden on heat maps, and the top margin increased. |
| 12 | Card headers can wrap. |
| 13 | `normalize_unicode()`. Tests cover these cases. |
| 14 | `ui.safe_url()` only allows http(s). Test: `test_story_card_blocks_unsafe_url_schemes_and_escapes_html`. |
| 15–18 | Rewritten, as listed in 3 above. |

## 5. AI response tests and results

The 9 scenarios from the brief were run against **real Groq calls** through the same pipeline the chat page uses
(`tests/live/ai_eval.py`). The answers are saved in `data/qa_ai/` (`NN_name.md` is the cleaned answer,
`.raw.txt` is the model output). Final run:

| # | Scenario | Model | Verified links | Checks | First token / total |
|---|---|---|---|---|---|
| 1 | Simple question ("Is the S&P up today?") | gpt-oss-120b | 0 (data only) | Concise, 1 sentence ✓ | 0.5 s / 0.6 s |
| 2 | Detailed US market analysis | gpt-oss-120b | 11 | Research structure, AI-view labels, tables ✓ | 1.7 s / 5.9 s |
| 3 | Why is gold moving | gpt-oss-20b | 1 | Driver windows correct, ⚠️ freshness note ✓ | 1.1 s / 1.3 s |
| 4 | Indian markets | gpt-oss-120b | 0 (data only) | Tables, STALE flag on 23 Nov bars ✓ | 0.6 s / 1.8 s |
| 5 | Geopolitics | gpt-oss-120b | 9 | AI-view labels ✓ | 0.9 s / 1.5 s |
| 6 | Specific company (Nvidia) | gpt-oss-120b | 6 | Company data plus news; the CEO-return story matches stored headlines ✓ | 1.1 s / 2.3 s |
| 7 | Semiconductor and AI trends | gpt-oss-20b | 4 | Uses Trends Radar stages and RS numbers ✓ | 1.3 s / 2.1 s |
| 8 | Multi-source comparison (US vs India vs Europe) | gpt-oss-120b | 6 | ✓ | 1.9 s / 3.9 s |
| 9 | Insufficient information (CPI consensus, Apple Q3 2027 EPS) | gpt-oss-20b | 0 | **Says "Not in today's data" and invents no numbers** ✓ | 1.2 s / 1.3 s |
| 10 | API failures and rate limits | — | — | See below ✓ | — |

Every run passed all of these checks: no raw JSON, no fenced whole answer, all tables well-formed, **100% of links
in the supplied source set**, and contexts of 8.8–10.8k characters.

**Scenario 10, failures and rate limits.** Tested with mocks (unit tests) and observed live:

- Groq 401 gives a clear key error.
- Groq 413/429 gives a "free tier ≈ 8,000 tokens/min, retry in a minute" message, and the next model is tried
  before the first token.
- Gemini daily-quota 429 marks the model as exhausted (persisted) and falls back. A live 503 was retried
  successfully.
- A stream that fails mid-answer raises "interrupted". The partial answer is discarded and an error is shown.
  It is **never replaced by a different answer**.
- With no AI keys configured, a second app instance shows a clear warning, the chat input is disabled, and the AI
  panel buttons are disabled. No placeholder text is generated.

**Formatting pipeline** (`tradingos/ai/formatting.py`, 20+ tests):

- Strips reasoning tags.
- Unwraps whole-answer code fences.
- Renders raw JSON as bullets.
- Repairs tables: separator row, blank lines, cell counts.
- Removes duplicated paragraphs.
- Normalises Unicode.
- Turns citation IDs into links and removes unverified links.
- Colours signed % moves green or red (skipping code, links and ranges).
- Closes an open code fence and drops half-written table rows while streaming.

**Chat UX (browser, live):** streaming cursor ✓, rendered Markdown with no raw `##` or `|---|` ✓, a table inside
the phone width ✓, 9 citation links opening in a new tab ✓, "Sources cited" list ✓, history after reload ✓,
identical question within 30 min served from the answer cache (no second AI call) ✓, no console errors ✓.

## 6. Mobile responsiveness results

`tests/e2e/ui_audit.py` checked 14 pages at **360, 375, 390, 430, 768, 1024, 1280, 1440 and 1920 px**: **126/126
clean**. Phone checks used touch emulation and a mobile user agent. Screenshots are in `data/qa_screens/`.

- **Navigation:** bottom tab bar on phones (≤767 px) with labelled icons, a 50 px touch height and an active-page
  highlight. The full menu sits behind the top-left button. The bar is hidden on the chat page so it doesn't cover
  the message box.
- **Layout:** two-up tile grid, stacked filters (Economic Calendar and News Archive filters are collapsed into
  expanders), Markdown tables scroll inside their own box, code blocks scroll, long words and URLs wrap.
- **Chat:** full-width messages, the input stays visible above the fold (checked: the input sits inside the
  viewport at 360/390), and tables and links fit.
- **Live Newsroom:** 16:9 player at full width, segmented region filter, fallback "Open live on YouTube" link.
- **Accessibility:** buttons are 44 px high on phones and tabs 40 px, `:focus-visible` outlines are shown,
  freshness dots have `aria-label`, the status strip is `role="status"`, links use `rel="noopener noreferrer"`,
  and nothing depends on hover (tooltips only duplicate visible information).

## 7. Desktop results

Same audit at 1024–1920 px: clean. The sidebar is grouped (Briefing · Markets · Intelligence · Research · System)
and uses an inset accent for the active page. Content width is capped at 1480 px, and there is one design-token
set (`:root` variables) for colour, spacing and radius. Green and red are used only for market moves.

## 8. API integration results

| Provider | Result |
|---|---|
| Groq | Live: streaming chat works on `openai/gpt-oss-120b`, falling back to `gpt-oss-20b` when the per-minute cap is hit. The free tier is 8,000 tokens/min and 1,000 requests/day (from the response headers). |
| Gemini | Live: 4 of 6 models were out of daily quota during testing. `gemini-3.1-flash-lite` answered (briefing and gold panel). |
| Yahoo Finance, FRED, RSS feeds | Live: pages populated, with freshness labels. |
| YouTube | 12 channel IDs verified against youtube.com, and the Bloomberg embed rendered. |
| X API | **Not tested live**: no `X_BEARER_TOKEN` is configured. The client was tested with mocks. |

## 9. Security issues discovered

| Issue | Status |
|---|---|
| `javascript:`/non-http feed URLs rendered as links | **Fixed** (`safe_url`) |
| HTML injection through headlines, summaries or X post text | Already escaped. Now covered by a test. |
| AI-fabricated links | **Fixed**: only URLs from the supplied data survive |
| API keys | Only from `.env` or Streamlit secrets. `.env` is git-ignored (checked with `git check-ignore`). No key patterns appear in tracked files, keys are never logged, and the Settings page never displays them. |
| Error leakage | Groq 413/429 bodies are no longer shown. Other errors are truncated and contain no secrets. |
| Input validation | Chat input is capped at 2,000 characters. Ticker regex, conversation-ID regex (`[0-9a-f]{16}`) and settings validation are in place. |
| Dependencies | `pip-audit` found no known vulnerabilities. |
| Server exposure | Streamlit binds to 127.0.0.1 (unchanged). There is no authentication, so don't expose the app publicly without a proxy that adds auth. |

## 10. Remaining limitations

- **X Intelligence needs a paid X API token.** Until `X_BEARER_TOKEN` is set, the page explains how to set it up,
  and the briefing says X is not configured. Live X behaviour is untested.
- **Free-tier AI limits.** Groq allows about 8k tokens/min, so chat context is capped at about 9k characters and
  back-to-back questions within a minute may switch to `gpt-oss-20b` or wait. Gemini allows about 20
  requests/day per model and was mostly exhausted during testing. Large briefings depend on Gemini; if Gemini
  is unavailable, Groq writes them from a shortened payload.
- **Citations depend on the model.** Data-only answers (for example scenarios 1 and 4) often cite no news. That
  is correct when only market data is used, but not guaranteed when news is used.
- **No consensus forecasts, FII/DII flows or MCX prices.** No authorised free source exists, so these are stated as
  unavailable rather than estimated.
- **Browser coverage:** Chromium only, with emulated phones. The on-screen keyboard, iOS Safari and real devices
  were not tested.
- **Streamlit internals:** the bottom navigation and some styling rely on Streamlit's `data-testid` and `st-key-*`
  hooks. Re-run `ui_audit.py` after upgrading Streamlit.
- **Screenshots:** Streamlit scrolls inside its own container, so "full-page" screenshots only show the viewport.
- **Database:** old trading tables and `longterm.db` are left in place (see section 2).
- **Live embeds:** many broadcasters are only live at certain hours or block embedding. The page always offers a
  link to the channel's live page.

## 11. Commands to run the application

```bash
uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env        # GROQ_API_KEY / GEMINI_API_KEY (optional), FRED/FINNHUB/FMP, X_BEARER_TOKEN (optional)
.venv/bin/streamlit run app.py
# scheduled briefings
.venv/bin/python scripts/intel_scheduler.py --list
*/15 * * * * cd ~/projects/Swinger && .venv/bin/python scripts/intel_scheduler.py >> data/reports/scheduler.log 2>&1
```

## 12. Commands to run the test suite

```bash
.venv/bin/python -m pytest -q                                          # 123 tests, offline, about 1 s
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/streamlit run app.py --server.port 8599 &
.venv/bin/python tests/e2e/ui_audit.py --out data/qa_screens            # 14 pages × 9 viewports
.venv/bin/python tests/e2e/chat_flow.py --width 390                     # LIVE: 1 AI request
.venv/bin/python tests/live/ai_eval.py --out data/qa_ai --pause 25      # LIVE: 9 AI requests
.venv/bin/python -m pyflakes app.py views tradingos tests
```
