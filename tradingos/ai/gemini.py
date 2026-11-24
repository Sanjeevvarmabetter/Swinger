"""Gemini integration via Google's official Gen AI SDK (`google-genai`).

Design rules:
  * Python computes every number. Gemini receives structured JSON and only interprets it.
  * Gemini is NOT assumed to have web access; it may only cite news items supplied in the payload.
  * API key comes from the environment (.env). It is never logged or sent to the browser.
  * Client-side rate limiting + retries with exponential backoff; friendly errors.
  * Every call is stored in ai_reports for auditability.
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from datetime import date, datetime
from typing import Any

from tradingos.config import load_config
from tradingos.db.models import AIReport
from tradingos.db.session import session_scope

log = logging.getLogger(__name__)

BASE_SYSTEM = """You are the research analyst inside a personal swing-trading research tool for one
retail trader (US stocks/ETFs, 2–4 week holds, small account, long-only, no leverage, no options).

NON-NEGOTIABLE RULES
1. Use ONLY the data in the JSON payload. Never invent prices, levels, statistics, news, dates or events.
   If something needed is missing, say "not in supplied data" and state what to verify.
2. All numbers (prices, indicators, position size, risk, R:R) were computed in Python. Quote them; do not
   recompute or alter them. Do not produce new price targets or levels that are not in the payload.
3. You have no live web access. Only reference news items present in the payload, citing source + timestamp.
4. Separate clearly: FACTS (from payload) vs INTERPRETATION (your reasoning) vs SPECULATION.
5. No certainty language, no guaranteed returns, no "will". Use conditional, probabilistic phrasing.
6. Challenge the idea: always include why it could fail, what invalidates it, whether it is extended,
   and whether reward justifies risk. Prefer "Wait"/"Avoid" when evidence is weak.
7. Never suggest increasing risk, leverage, averaging down, or using long-term investments to fund trades.
8. Be concise and structured with markdown headings and bullets. This is research, not financial advice.
"""

TASKS = {
    "market_analysis": """Write a DAILY US MARKET INTELLIGENCE BRIEF with these sections:
1. Overall market direction (use regime + index data). 2. Bullish developments. 3. Bearish developments.
4. Strongest & weakest sectors (from sector table). 5. Macro picture (from macro table; note dates).
6. Geopolitical developments (only from supplied headlines; explain plausible sector impact as interpretation).
7. Upcoming catalysts (only supplied events/earnings). 8. Potential opportunity areas (sectors/themes, not
trade calls). 9. Risks to watch. Cite each news-based claim as [Source, YYYY-MM-DD HH:MM UTC](url).""",
    "stock_analysis": """Analyse this stock for a 2–4 week swing trade. Sections: Snapshot (facts), Trend & momentum,
Relative strength & sector context, Fundamentals (only supplied fields), Recent news (cite), Upcoming catalysts &
earnings risk, Bull case, Bear case, What would make this attractive (specific conditions using supplied
levels), Verdict suggestion (Watch / Wait / Avoid / Plan eligible) with reasoning.""",
    "technical_analysis": """Interpret the technical snapshot. Explain: 1 current trend, 2 key supports, 3 key resistances,
4 momentum, 5 volume confirmation, 6 possible entry zones (ONLY using supplied levels/MAs), 7 invalidation level,
8 bullish scenario, 9 bearish scenario. Mention daily vs weekly alignment if both are supplied.""",
    "earnings_analysis": """Assess the earnings/fundamental data. Cover revenue growth, EPS, margins, cash flow, debt,
valuation, guidance/analyst expectations ONLY if supplied. State whether the data strengthens or weakens a
swing-trading thesis, and explicitly flag overnight gap risk if the next earnings date falls within ~4 weeks.""",
    "trade_plan_review": """Critically review this trade plan as a skeptical risk-aware mentor. Sections: Thesis quality,
Entry trigger quality, Stop placement (is it a true invalidation?), Targets vs supplied resistance, Is the stock
overextended?, Does reward justify risk (use supplied R:R and costs)?, Why this trade might FAIL (at least 3
reasons), What would invalidate the thesis, Additional confirmation needed, Final: agree or disagree with the
deterministic verdict and why. You may NOT upgrade a verdict the risk engine marked Avoid.""",
    "risk_review": """Review portfolio-level risk: open positions, aggregate open risk vs limit, concentration (sector/theme
correlation), earnings exposure, regime. List concrete risk-reduction considerations. Never suggest adding risk.""",
    "weekly_performance_review": """Write a trading performance review for the period. Sections: Summary stats (quote),
What went well, What went wrong, Rule/risk violations, Repeated mistakes (from tags/diagnostics), Setup observations,
One or two process changes to test next period. If the sample is small, say conclusions are anecdotal.""",
    "news_impact": """For each supplied headline, classify: confirmed fact / analyst interpretation / speculation; likely
affected sectors/tickers; plausible direction and why (interpretation). Keep each item to 1–2 lines and cite.""",
}

INTEL_SYSTEM = """You are the research desk inside a personal GLOBAL MARKET INTELLIGENCE terminal for one reader:
an India-based professional who invests in US and Indian markets, follows gold, geopolitics, AI and semiconductors,
and works full-time — so every sentence must earn its place.

NON-NEGOTIABLE RULES
1. Use ONLY the JSON payload. You have no web access. Never invent prices, levels, statistics, quotes, events, dates,
   forecasts, consensus figures or sources. If something is missing say "not in today's data" — do not fill gaps.
2. Every number was computed in Python; quote it exactly with its as-of date. Flag anything whose freshness is not
   "Current" or "Intraday" as stale.
3. Cite every news-based claim inline as [Source, DD Mon HH:MM UTC](url) using only URLs from the payload.
4. Label each claim with exactly one tag: [FACT] (official/confirmed source), [DATA] (market or economic data from
   the payload), [REPORTED] (news media report), [OPINION] (analyst/commentator view), [AI VIEW] (your
   interpretation), [UNVERIFIED] (speculation, rumour, single unconfirmed source).
5. Explain WHY each development matters (transmission channel → which markets/sectors/assets), not just what happened.
   Prefer "could", "may", "historically" — never certainty, never trade instructions or price targets.
6. Do not treat older items as new: compare published timestamps with the briefing time.
7. Be concise, specific and skimmable: markdown headings, short bullets, no filler, no generic market platitudes.
"""

INTEL_TASKS = {
    "daily_briefing": """Write the {edition_title} for {edition_date} ({edition_time}). Target reading time 10–15 minutes,
with a 3-minute executive summary at the top.

Structure (omit a section only if the payload has nothing for it — then write one line saying so):
## ⏱ 3-minute executive summary — 5–10 bullets, most important first, each with why it matters.
## 🔴 MUST KNOW · ## 🟠 IMPORTANT · ## 🔵 INTERESTING · ## ⚪ IGNORE FOR NOW (one line each)
  Use the deterministic `tier` field on ranked stories as the starting point; you may move a story up or down one
  tier only with a stated reason.
Then the detailed sections, in this order, focusing on what is relevant to this edition ({edition_focus}):
1 US markets overnight · 2 Indian markets · 3 Asia & Europe · 4 Gold & commodities · 5 Geopolitics ·
6 Economy & central banks · 7 Financial X discussions · 8 Major company news · 9 Technology & AI ·
10 Upcoming earnings & economic events (IST times as supplied) · 11 Emerging investment themes ·
12 Bullish developments · 13 Bearish developments · 14 Risks & uncertainties · 15 What to watch next.
For section 5 use `geopolitics` (keyword-matched theaters with event evidence; `transmission_framework` is static
analysis — present it as interpretation, never as news). For section 6 use `central_banks` and `economic_calendar`
(quote actuals only where supplied; forecasts are unavailable — say so, never estimate). For section 11 use
`trends_radar` stages and their relative-strength numbers.
For section 7: the payload has no X/Twitter data yet — say "X integration not yet enabled" and nothing else.
For market moves, quote the supplied numbers and freshness. Use the supplied risk-appetite checklist and gold
driver readings rather than inventing explanations.""",
    "us_market_analyst": """Act as the US Market Analyst. Explain the current US market environment from the payload:
trend & breadth, risk appetite checklist, sector and theme leadership (what it implies about the market's narrative),
rates/credit/dollar backdrop, notable news, upcoming catalysts, and the 3–5 things that would change the picture.""",
    "india_market_analyst": """Act as the Indian Market Analyst. Explain the Indian market environment from the payload:
index trend, breadth across large/mid/small caps, sector leadership, India VIX, USD/INR, how global factors
(US yields, dollar, crude, risk appetite) transmit to Indian equities, notable Indian news (RBI/SEBI/corporate),
and what to monitor. State clearly that FII/DII flow data is not in the payload.""",
    "gold_analyst": """Act as the Gold & Commodities Analyst. Using the payload explain: why gold is moving (only via the
supplied driver table, correlations and positioning — say when supplied drivers do NOT explain the move);
short-term (1W/1M) vs long-term structural picture (1Y, 200DMA, 52w high); CFTC positioning/crowding; INR gold;
silver, copper, oil and what they say about growth/inflation; what could change the outlook; what to monitor.
Clearly note what is NOT measured here (ETF flows, central-bank purchases, physical demand).""",
    "geopolitical_analyst": """Act as the Geopolitical Analyst for the theater in the payload. For the most important
1–4 events answer: 1 What happened? 2 When? 3 Who is involved? 4 What is confirmed? 5 What is still uncertain?
6 Why does it matter economically? 7 Which countries are affected? 8 Which sectors? 9 Which commodities?
10 Possible market transmission channels (cite the supplied market reaction table — say if markets are NOT reacting)?
11 What to monitor next? Use `framework` fields only as interpretation and label them [AI VIEW]/[FRAMEWORK].
Never upgrade single-source or speculative reports to fact. End with an overall escalation/de-escalation read and
what evidence would change it.""",
    "trends_analyst": """Act as the Trends Radar analyst. For the supplied theme(s): explain the current development
using only the supplied news and metrics, why it matters, the evidence of momentum (quote RS, extension, breadth,
attention), the rule-based stage and whether you agree with it (with reasons), potential beneficiaries and losers
(framework fields, labelled as such), the main risks, and what would invalidate the trend. Never name price targets
or make buy/sell calls.""",
    "news_summary": """Summarise this developing story thread for a busy reader: what is known (with source/time
citations), how the story evolved across updates, what is confirmed vs reported vs speculative, why it matters to
markets, and what to watch. Max 200 words.""",
    "global_macro_analyst": """Act as the Global Macro Analyst. Explain cross-market conditions: risk-on/off checklist,
rates and the dollar, FX (JPY, INR, EUR), regional equity divergence (US vs Europe vs Asia vs India), commodities,
central-bank headlines in the payload, and the main macro risks. End with 'What would change my read'.""",
}


# Tried in order after GEMINI_MODEL. On the free tier each model has its OWN daily request quota (e.g. 20/day),
# so a wider chain keeps AI features working after one model's allowance is used. Verified available to the
# configured key on 2026-11-24 via models.list().
FALLBACK_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]  # gemini-2.5-* are listed for the key but returned 404 on generateContent (2026-11-24)
_EXHAUSTED_KEY = "gemini|exhausted_until"   # disk-cached {model: unix_ts} shared by the app and scheduler


def parse_retry_seconds(message: str) -> float | None:
    """Extract Google's suggested retry delay, e.g. 'Please retry in 15h58m56.37s' or "retryDelay': '41s'"."""
    m = re.search(r"retry in\s+(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:([\d.]+)s)?", message, re.I)
    if m and any(m.groups()):
        h, mi, sec = (float(x) if x else 0.0 for x in m.groups())
        return h * 3600 + mi * 60 + sec
    m = re.search(r"retryDelay['\"]?:\s*['\"]?([\d.]+)s", message)
    return float(m.group(1)) if m else None


def _exhausted() -> dict[str, float]:
    from tradingos.data import cache
    d = cache.get(_EXHAUSTED_KEY, 48 * 3600) or {}
    now = time.time()
    return {m: t for m, t in d.items() if t > now}


def _mark_exhausted(model: str, seconds: float) -> None:
    from tradingos.data import cache
    d = _exhausted()
    d[model] = time.time() + seconds
    cache.put(_EXHAUSTED_KEY, d)


def quota_status() -> list[dict]:
    """Models currently known to be out of quota and when they reset (for the UI)."""
    now = time.time()
    return [{"model": m, "resets_in_hours": round((t - now) / 3600, 1)} for m, t in sorted(_exhausted().items())]


class GeminiError(RuntimeError):
    pass


def to_jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else round(obj, 4)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, "item"):  # numpy scalar
        return to_jsonable(obj.item())
    if hasattr(obj, "to_dict"):  # pandas
        try:
            return to_jsonable(obj.to_dict("records"))
        except TypeError:
            return to_jsonable(obj.to_dict())
    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict
        return to_jsonable(asdict(obj))
    return obj


class GeminiClient:
    _lock = threading.Lock()
    _last_call = 0.0

    def __init__(self):
        self.cfg = load_config()
        self._client = None
        self.active_model = self.cfg.gemini_model

    @property
    def configured(self) -> bool:
        return self.cfg.gemini_configured

    def client(self):
        if not self.configured:
            raise GeminiError("Gemini is not configured. Add GEMINI_API_KEY to your .env file "
                              "(get a key at https://aistudio.google.com/apikey) and restart the app.")
        if self._client is None:
            from google import genai
            from google.genai import types
            self._client = genai.Client(api_key=self.cfg.gemini_api_key,
                                        http_options=types.HttpOptions(timeout=120_000))
        return self._client

    def _throttle(self):
        with GeminiClient._lock:
            wait = self.cfg.gemini_min_interval - (time.time() - GeminiClient._last_call)
            if wait > 0:
                time.sleep(wait)
            GeminiClient._last_call = time.time()

    def generate(self, prompt: str, system: str = BASE_SYSTEM, temperature: float = 0.3,
                 max_output_tokens: int = 8192) -> str:
        """Try the configured model, then FALLBACK_MODELS.

        Quota-aware: a 429 whose retry delay is long (daily free-tier cap) marks that model exhausted until reset
        — persisted on disk so neither the app nor the scheduler wastes further requests on it. Short 429s
        (per-minute limits) wait the suggested delay once (≤30 s). 503/500 get one quick retry, then fall back.
        """
        from google.genai import errors, types
        client = self.client()
        config = types.GenerateContentConfig(system_instruction=system, temperature=temperature,
                                             max_output_tokens=max_output_tokens)
        chain = list(dict.fromkeys([self.cfg.gemini_model, *FALLBACK_MODELS]))
        exhausted = _exhausted()
        skipped = [m for m in chain if m in exhausted]
        candidates = [m for m in chain if m not in exhausted]
        outcomes: dict[str, str] = {m: f"daily quota used — resets in {(exhausted[m] - time.time()) / 3600:.1f}h"
                                    for m in skipped}
        for model in candidates:
            for attempt in range(2):
                self._throttle()
                try:
                    resp = client.models.generate_content(model=model, contents=prompt, config=config)
                    text = getattr(resp, "text", None)
                    if not text:
                        reason = ""
                        try:
                            reason = str(resp.candidates[0].finish_reason)
                        except Exception:
                            pass
                        outcomes[model] = f"empty response {reason}".strip()
                        break
                    self.active_model = model
                    if model != self.cfg.gemini_model:
                        log.info("Gemini answered with fallback model %s", model)
                    return text
                except errors.ClientError as e:
                    code, msg = getattr(e, "code", None), str(e)
                    if code in (401, 403):
                        raise GeminiError("Gemini rejected the API key (401/403). Check GEMINI_API_KEY in .env.") from e
                    if code == 404:
                        _mark_exhausted(model, 24 * 3600)   # don't spend calls on it again today
                        outcomes[model] = "not available to this key (404)"
                        break
                    if code == 429:
                        delay = parse_retry_seconds(msg)
                        daily = "per day" in msg.lower() or (delay is not None and delay > 120)
                        if daily:
                            _mark_exhausted(model, delay or 6 * 3600)
                            outcomes[model] = (f"daily quota used — resets in {(delay or 0) / 3600:.1f}h"
                                               if delay else "daily quota used")
                            break
                        if attempt == 0 and (delay or 5) <= 30:
                            time.sleep(delay or 5)
                            continue
                        outcomes[model] = "rate-limited (per-minute)"
                        break
                    if code == 400 and "token" in msg.lower():
                        raise GeminiError(f"Prompt too large for {model}: {msg[:200]}") from e
                    outcomes[model] = f"HTTP {code}: {getattr(e, 'message', msg)[:100]}"
                    break
                except errors.ServerError as e:
                    outcomes[model] = f"overloaded (HTTP {getattr(e, 'code', 503)})"
                    if attempt == 0:
                        time.sleep(2)
                        continue
                    break
                except Exception as e:  # network
                    outcomes[model] = f"{type(e).__name__}: {str(e)[:80]}"
                    if attempt == 0:
                        time.sleep(2)
                        continue
                    break
        detail = "; ".join(f"{m}: {o}" for m, o in outcomes.items())
        daily_out = [m for m, o in outcomes.items() if o.startswith("daily quota")]
        hint = (" Your key is on the free tier (about 20 requests/day per model); quotas reset at midnight US "
                "Pacific time. Enabling billing on the Google AI Studio project raises the limits."
                if daily_out else " Retry in a few minutes.")
        raise GeminiError(f"No Gemini model could answer — {detail}.{hint}")

    def chat(self, history: list[dict], user_msg: str, context: dict | None = None) -> str:
        """Multi-turn chat. history = [{'role': 'user'|'model', 'text': ...}]."""
        sys = BASE_SYSTEM + "\nYou are in CHAT mode. The JSON CONTEXT below is the only market data you may use.\n"
        if context:
            sys += "CONTEXT:\n" + json.dumps(to_jsonable(context), default=str)[:60_000]
        convo = "\n".join(f"{'USER' if h['role'] == 'user' else 'ASSISTANT'}: {h['text']}" for h in history[-12:])
        prompt = (f"Conversation so far:\n{convo}\n\n" if convo else "") + f"USER: {user_msg}\nASSISTANT:"
        return self.generate(prompt, system=sys, temperature=0.4)


_CLIENT: GeminiClient | None = None


def get_client() -> GeminiClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = GeminiClient()
    return _CLIENT


def _run(kind: str, payload: dict, subject: str = "", extra_instructions: str = "",
         task_text: str | None = None, system: str = BASE_SYSTEM, max_output_tokens: int = 8192) -> str:
    data = to_jsonable(payload)
    body = json.dumps(data, default=str, indent=1)
    if len(body) > 120_000:
        body = body[:120_000] + "\n...[truncated]"
    prompt = f"TASK:\n{task_text or TASKS[kind]}\n{extra_instructions}\n\nDATA (JSON, computed by Python):\n{body}"
    client = get_client()
    text = client.generate(prompt, system=system, max_output_tokens=max_output_tokens)
    with session_scope() as s:
        s.add(AIReport(kind=kind, subject=subject, model=client.active_model,
                       input_json=body[:200_000], output_text=text))
    return text


def intel_analysis(kind: str, payload: dict, subject: str = "", **fmt) -> str:
    """Run one of the INTEL_TASKS with the intelligence-desk system prompt."""
    task = INTEL_TASKS[kind].format(**fmt) if fmt else INTEL_TASKS[kind]
    return _run(kind, payload, subject or kind, task_text=task, system=INTEL_SYSTEM, max_output_tokens=16384)


# ---- public AI functions (each receives structured data from Python) ----
def market_analysis(payload: dict) -> str:
    return _run("market_analysis", payload, "US market")


def stock_analysis(ticker: str, payload: dict) -> str:
    return _run("stock_analysis", payload, ticker)


def technical_analysis(ticker: str, payload: dict) -> str:
    return _run("technical_analysis", payload, ticker)


def earnings_analysis(ticker: str, payload: dict) -> str:
    return _run("earnings_analysis", payload, ticker)


def trade_plan_review(ticker: str, payload: dict) -> str:
    return _run("trade_plan_review", payload, ticker)


def risk_review(payload: dict) -> str:
    return _run("risk_review", payload, "portfolio")


def weekly_performance_review(payload: dict) -> str:
    return _run("weekly_performance_review", payload, payload.get("period", ""))


def news_impact(payload: dict) -> str:
    return _run("news_impact", payload, "news")


def test_connection() -> tuple[bool, str]:
    try:
        c = get_client()
        txt = c.generate("Reply with exactly: OK", system="You are a connectivity check.",
                         temperature=0, max_output_tokens=20)
        return True, f"Connected to {c.active_model}: {txt.strip()[:40]}"
    except (GeminiError, Exception) as e:
        return False, str(e)


def recent_reports(kind: str | None = None, subject: str | None = None, limit: int = 20) -> list[AIReport]:
    from sqlalchemy import select
    with session_scope() as s:
        q = select(AIReport)
        if kind:
            q = q.where(AIReport.kind == kind)
        if subject:
            q = q.where(AIReport.subject == subject)
        return list(s.scalars(q.order_by(AIReport.created_at.desc()).limit(limit)).all())
