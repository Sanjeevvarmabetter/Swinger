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
from typing import Any, Iterator

from tradingos.config import load_config
from tradingos.db.models import AIReport
from tradingos.db.session import session_scope

log = logging.getLogger(__name__)

BASE_SYSTEM = """You are the research desk inside a personal GLOBAL MARKET INTELLIGENCE terminal (US and Indian markets,
gold and commodities, geopolitics, macro, technology). This is research, not financial advice.

NON-NEGOTIABLE RULES
1. Use ONLY the data in the JSON payload. Never invent prices, levels, statistics, news, dates, events or sources.
   If something needed is missing, say "Not in today's data" and state what to verify and where.
2. All numbers were computed in Python. Quote them exactly; do not recompute or alter them.
3. You have no live web access. Only reference news items present in the payload, citing source + timestamp.
4. Separate clearly: facts (from payload) vs interpretation (yours) vs speculation.
5. No certainty language, no guaranteed returns, no trade instructions, no price targets.
6. Be concise and structured with markdown headings and bullets.
"""

TASKS = {
    "news_impact": """For each supplied headline, classify: confirmed fact / analyst interpretation / speculation; likely
affected sectors/markets; plausible direction and why (interpretation). Keep each item to 1–2 lines and cite.""",
}

RESEARCH_SYSTEM = """You are the research desk of a personal GLOBAL MARKET INTELLIGENCE terminal. The reader is an
India-based professional who follows US and Indian markets, gold, geopolitics, macro, AI and semiconductors.

GROUNDING — NON-NEGOTIABLE
1. Use ONLY the JSON CONTEXT supplied with each question (market snapshot, ranked news, calendars, company data).
   You have no web access. Never invent prices, figures, events, dates, quotes, forecasts or sources.
2. Quote numbers exactly as supplied with their as-of date. If a reading is marked stale, say so.
3. If the context does not contain what the question needs, say plainly: "**Not in today's data:** …" and name the
   kind of source that would answer it. Do not fill gaps from memory. General background knowledge (how a mechanism
   works, e.g. why real yields matter for gold) is allowed but must be labelled **AI view**.
4. Every news item and official document in CONTEXT has an "id" such as N3, C1, G2 or B1. Cite by writing the id in
   square brackets right after the claim, e.g. "Gold fell 2.6% [N3]." or "[N1][N4]". Never write URLs or link
   syntax yourself and never invent ids. Market-data numbers need no id: state the as-of date instead. Do NOT write
   a "Sources" section — the app turns the ids into links and appends the verified source list automatically.
5. Label interpretation: begin interpretive bullets or sentences with "**AI view:**". Facts from the data need a
   citation or an as-of date instead. Never present speculation or a single-source report as confirmed.
6. No certainty language, no buy/sell instructions, no price targets.

FORMAT — the answer is rendered as Markdown in a research terminal (desktop and phone)
- Never wrap the whole answer in a code fence. Never output JSON unless the user explicitly asks for JSON.
- Match length to the question. A simple question gets a direct 2–6 sentence answer or a few bullets — no report
  scaffolding. An analytical question gets a research note using `##` headings chosen from, in this order:
  Executive Summary · What Happened · Why It Happened · Market Impact · Global Implications · Bullish Factors ·
  Bearish Factors · Risks and Uncertainties · What to Watch Next. Skip any section the data cannot support.
- Start analytical answers with a 2–4 bullet **Executive Summary**. End them with **Key takeaways** only when useful.
- Tables: standard GitHub Markdown — header row, a |---| separator row, one row per line, at most 5 columns, short
  cells, a blank line before and after. Use tables for comparisons of 3+ instruments, not for single numbers.
- Numbers: signed percentages (+1.24%, -0.85%), currency symbols with thousands separators ($4,215.30, ₹82,450),
  yields in % (4.91%). Keep the precision supplied.
- Use > ⚠️ blockquotes for important warnings (stale data, unconfirmed reports, missing data).
- Short paragraphs, bold only for key terms, no emojis other than ⚠️.
"""

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
For section 7 use `x_intelligence` if present; if it says X is not configured, write one line saying so and nothing else.
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


AIError = GeminiError

GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
]


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
        self.active_model = self.cfg.groq_model if self.cfg.groq_configured else self.cfg.gemini_model

    @property
    def configured(self) -> bool:
        return self.cfg.ai_configured

    def client(self):
        if not self.cfg.gemini_configured:
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

    def _generate_groq(self, prompt: str, system: str, temperature: float, max_output_tokens: int) -> str:
        """Query Groq OpenAI-compatible chat API with automatic model fallback."""
        import requests
        headers = {
            "Authorization": f"Bearer {self.cfg.groq_api_key}",
            "Content-Type": "application/json",
        }
        models = list(dict.fromkeys([self.cfg.groq_model, *GROQ_MODELS]))
        last_err = None
        for m in models:
            payload = {
                "model": m,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "max_tokens": min(max_output_tokens, 8192),
            }
            try:
                resp = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self.active_model = f"groq/{m}"
                    return data["choices"][0]["message"]["content"]
                last_err = (f"Groq rate/size limit ({m}): the free tier allows about 8,000 tokens per minute — "
                            "retry in a minute." if resp.status_code in (413, 429)
                            else f"Groq HTTP {resp.status_code} ({m}): {resp.text[:150]}")
                if resp.status_code in (401, 403):
                    raise GeminiError("Groq rejected the API key (401/403). Check GROQ_API_KEY.")
            except GeminiError:
                raise
            except Exception as e:  # noqa: BLE001
                last_err = f"Groq request error ({m}): {type(e).__name__}"
        raise GeminiError(last_err or "Groq generation failed.")

    def _gemini_chain(self) -> tuple[list[str], dict[str, str]]:
        chain = list(dict.fromkeys([self.cfg.gemini_model, *FALLBACK_MODELS]))
        exhausted = _exhausted()
        outcomes = {m: f"daily quota used — resets in {(exhausted[m] - time.time()) / 3600:.1f}h"
                    for m in chain if m in exhausted}
        return [m for m in chain if m not in exhausted], outcomes

    @staticmethod
    def _gemini_error_action(model: str, e: Exception, attempt: int, outcomes: dict[str, str]) -> str:
        """Classify a Gemini exception → 'retry' (same model) or 'next' (fall back). Fatal errors raise GeminiError."""
        from google.genai import errors
        if isinstance(e, errors.ClientError):
            code, msg = getattr(e, "code", None), str(e)
            if code in (401, 403):
                raise GeminiError("Gemini rejected the API key (401/403). Check GEMINI_API_KEY in .env.") from e
            if code == 404:
                _mark_exhausted(model, 24 * 3600)   # don't spend calls on it again today
                outcomes[model] = "not available to this key (404)"
                return "next"
            if code == 429:
                delay = parse_retry_seconds(msg)
                if "per day" in msg.lower() or (delay is not None and delay > 120):
                    _mark_exhausted(model, delay or 6 * 3600)
                    outcomes[model] = (f"daily quota used — resets in {(delay or 0) / 3600:.1f}h"
                                       if delay else "daily quota used")
                    return "next"
                if attempt == 0 and (delay or 5) <= 30:
                    time.sleep(delay or 5)
                    return "retry"
                outcomes[model] = "rate-limited (per-minute)"
                return "next"
            if code == 400 and "token" in msg.lower():
                raise GeminiError(f"Prompt too large for {model}: {msg[:200]}") from e
            outcomes[model] = f"HTTP {code}: {getattr(e, 'message', msg)[:100]}"
            return "next"
        if isinstance(e, errors.ServerError):
            outcomes[model] = f"overloaded (HTTP {getattr(e, 'code', 503)})"
        else:   # network
            outcomes[model] = f"{type(e).__name__}: {str(e)[:80]}"
        if attempt == 0:
            time.sleep(2)
            return "retry"
        return "next"

    @staticmethod
    def _gemini_failure(outcomes: dict[str, str]) -> GeminiError:
        detail = "; ".join(f"{m}: {o}" for m, o in outcomes.items())
        daily_out = [m for m, o in outcomes.items() if o.startswith("daily quota")]
        hint = (" Your key is on the free tier (about 20 requests/day per model); quotas reset at midnight US "
                "Pacific time. Enabling billing on the Google AI Studio project raises the limits."
                if daily_out else " Retry in a few minutes.")
        return GeminiError(f"No Gemini model could answer — {detail}.{hint}")

    def _generate_gemini(self, prompt: str, system: str = BASE_SYSTEM, temperature: float = 0.3,
                         max_output_tokens: int = 8192) -> str:
        """Try the configured model, then FALLBACK_MODELS.

        Quota-aware: a 429 whose retry delay is long (daily free-tier cap) marks that model exhausted until reset
        — persisted on disk so neither the app nor the scheduler wastes further requests on it. Short 429s
        (per-minute limits) wait the suggested delay once (≤30 s). 503/500 get one quick retry, then fall back.
        """
        from google.genai import types
        client = self.client()
        config = types.GenerateContentConfig(system_instruction=system, temperature=temperature,
                                             max_output_tokens=max_output_tokens)
        candidates, outcomes = self._gemini_chain()
        for model in candidates:
            for attempt in range(2):
                self._throttle()
                try:
                    resp = client.models.generate_content(model=model, contents=prompt, config=config)
                except Exception as e:  # noqa: BLE001 — classified below
                    if self._gemini_error_action(model, e, attempt, outcomes) == "retry":
                        continue
                    break
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
        raise self._gemini_failure(outcomes)

    # ------------------------------------------------------------------ research chat (streaming)
    @staticmethod
    def _chat_system(context: dict | None) -> str:
        sys_prompt = RESEARCH_SYSTEM
        if context:
            sys_prompt += ("\nCONTEXT (JSON — the only market data and news you may use):\n"
                           + json.dumps(to_jsonable(context), default=str)[:60_000])
        return sys_prompt

    @staticmethod
    def _history_msgs(history: list[dict]) -> list[dict]:
        """Last turns as role/content pairs. Error entries are never sent back to the model."""
        out = []
        for h in history[-6:]:
            if h.get("role") not in ("user", "assistant", "model"):
                continue
            # Older turns are shortened: free-tier providers cap tokens per request (Groq on-demand: 8k TPM).
            out.append({"role": "user" if h["role"] == "user" else "assistant", "content": str(h.get("text", ""))[:1500]})
        return out

    def _groq_stream(self, history: list[dict], user_msg: str, context: dict | None) -> Iterator[str]:
        import requests
        headers = {"Authorization": f"Bearer {self.cfg.groq_api_key}", "Content-Type": "application/json"}
        messages = [{"role": "system", "content": self._chat_system(context)}, *self._history_msgs(history),
                    {"role": "user", "content": user_msg}]
        last_err = None
        for m in dict.fromkeys([self.cfg.groq_model, *GROQ_MODELS]):
            payload = {"model": m, "messages": messages, "temperature": 0.35, "max_tokens": 6144, "stream": True}
            try:
                resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload,
                                     stream=True, timeout=(10, 120))
            except Exception as e:  # noqa: BLE001
                last_err = f"Groq request error ({m}): {type(e).__name__}"
                continue
            if resp.status_code in (401, 403):
                raise GeminiError("Groq rejected the API key (401/403). Check GROQ_API_KEY.")
            if resp.status_code != 200:
                if resp.status_code in (413, 429):
                    last_err = (f"Groq rate limit reached ({m}: free tier allows about 8,000 tokens per minute) — "
                                "wait a minute and ask again.")
                else:
                    last_err = f"Groq HTTP {resp.status_code} ({m}): {resp.text[:150]}"
                continue
            self.active_model = f"groq/{m}"
            resp.encoding = "utf-8"   # SSE has no charset header; requests would otherwise assume ISO-8859-1
            yielded = False
            try:
                for line in resp.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0]["delta"].get("content")
                    except (ValueError, KeyError, IndexError, TypeError):
                        continue
                    if delta:
                        yielded = True
                        yield delta
            except Exception as e:  # noqa: BLE001
                if yielded:
                    raise GeminiError(f"The response was interrupted ({type(e).__name__}). Ask again to retry.") from e
                last_err = f"Groq stream error ({m}): {type(e).__name__}"
                continue
            if yielded:
                return
            last_err = f"Groq returned an empty response ({m})"
        raise GeminiError(last_err or "Groq chat failed.")

    def _gemini_stream(self, history: list[dict], user_msg: str, context: dict | None) -> Iterator[str]:
        from google.genai import types
        client = self.client()
        config = types.GenerateContentConfig(system_instruction=self._chat_system(context), temperature=0.35,
                                             max_output_tokens=8192)
        convo = "\n\n".join(f"{'USER' if h['role'] == 'user' else 'ASSISTANT'}: {h['content']}"
                             for h in self._history_msgs(history))
        prompt = (f"Conversation so far:\n{convo}\n\n" if convo else "") + f"USER: {user_msg}\nASSISTANT:"
        candidates, outcomes = self._gemini_chain()
        for model in candidates:
            for attempt in range(2):
                self._throttle()
                yielded = False
                try:
                    stream = (client.models.generate_content_stream(model=model, contents=prompt, config=config)
                              if hasattr(client.models, "generate_content_stream")
                              else [client.models.generate_content(model=model, contents=prompt, config=config)])
                    for chunk in stream:
                        text = getattr(chunk, "text", None)
                        if text:
                            yielded = True
                            self.active_model = model
                            yield text
                except GeminiError:
                    raise
                except Exception as e:  # noqa: BLE001
                    if yielded:
                        raise GeminiError(f"The response was interrupted ({type(e).__name__}). Ask again to retry.") from e
                    if self._gemini_error_action(model, e, attempt, outcomes) == "retry":
                        continue
                    break
                if yielded:
                    return
                outcomes[model] = "empty response"
                break
        raise self._gemini_failure(outcomes)

    def generate(self, prompt: str, system: str = BASE_SYSTEM, temperature: float = 0.3,
                 max_output_tokens: int = 8192) -> str:
        """Route generation to configured AI provider (Groq or Gemini)."""
        # If test or caller injected a Gemini mock object on self._client, use Gemini flow
        if self._client is not None and hasattr(self._client, "models"):
            return self._generate_gemini(prompt, system, temperature, max_output_tokens)

        # Route to Groq if configured (preferred / active)
        if self.cfg.groq_configured and (self.cfg.ai_provider in ("groq", "auto") or not self.cfg.gemini_configured):
            try:
                return self._generate_groq(prompt, system, temperature, max_output_tokens)
            except Exception as e:
                if self.cfg.gemini_configured and self.cfg.ai_provider == "auto":
                    log.warning("Groq generation failed (%s), falling back to Gemini", e)
                    return self._generate_gemini(prompt, system, temperature, max_output_tokens)
                raise

        # Route to Gemini if configured
        if self.cfg.gemini_configured:
            return self._generate_gemini(prompt, system, temperature, max_output_tokens)

        # Route to Groq fallback if gemini was requested but not configured
        if self.cfg.groq_configured:
            return self._generate_groq(prompt, system, temperature, max_output_tokens)

        raise GeminiError(
            "No AI provider configured. Add GROQ_API_KEY (recommended, free) or GEMINI_API_KEY "
            "to your .env file or Streamlit secrets."
        )

    def chat_stream(self, history: list[dict], user_msg: str, context: dict | None = None) -> Iterator[str]:
        """Stream a research-desk answer, routed to the active provider (Groq preferred, Gemini fallback).

        Provider fallback only happens before the first token; a failure mid-answer raises GeminiError so the UI
        never silently splices two different answers together.
        """
        if self._client is not None and hasattr(self._client, "models"):
            yield from self._gemini_stream(history, user_msg, context)
            return
        if self.cfg.groq_configured and (self.cfg.ai_provider in ("groq", "auto") or not self.cfg.gemini_configured):
            started = False
            try:
                for piece in self._groq_stream(history, user_msg, context):
                    started = True
                    yield piece
                return
            except GeminiError as e:
                if started or not (self.cfg.gemini_configured and self.cfg.ai_provider == "auto"):
                    raise
                log.warning("Groq chat failed (%s), falling back to Gemini", e)
            yield from self._gemini_stream(history, user_msg, context)
            return
        if self.cfg.gemini_configured:
            yield from self._gemini_stream(history, user_msg, context)
            return
        raise GeminiError("No AI provider configured. Add GROQ_API_KEY or GEMINI_API_KEY to .env or Streamlit secrets.")

    def chat(self, history: list[dict], user_msg: str, context: dict | None = None) -> str:
        """Non-streaming convenience wrapper around chat_stream()."""
        return "".join(self.chat_stream(history, user_msg, context))


AIClient = GeminiClient


_CLIENT: GeminiClient | None = None


GROQ_PAYLOAD_BUDGET = 15_000   # chars of compact JSON ≈ 5k tokens; Groq on-demand tier allows ~8k tokens/minute


def shrink_json(data: Any, max_chars: int) -> tuple[Any, bool]:
    """Shrink a JSON-able structure below max_chars without breaking it: repeatedly halve the largest list (lists
    in payloads are ranked, so the head is kept), then shorten the longest string. Returns (data, was_shrunk)."""
    import copy
    d = copy.deepcopy(data)

    def size(o) -> int:
        return len(json.dumps(o, default=str, separators=(",", ":")))

    if size(d) <= max_chars:
        return d, False
    for _ in range(200):
        if size(d) <= max_chars:
            break
        best, best_sz, best_parent, best_key = None, 0, None, None
        stack = [(d, None, None)]
        while stack:
            node, parent, key = stack.pop()
            if isinstance(node, list) and len(node) > 1:
                sz = size(node)
                if sz > best_sz:
                    best, best_sz, best_parent, best_key = node, sz, parent, key
            children = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else []
            for k, v in children:
                if isinstance(v, (dict, list)):
                    stack.append((v, node, k))
        if best is not None:
            best_parent[best_key] = best[: max(1, len(best) // 2)]
            continue
        # no shrinkable list left: shorten the longest string
        longest, lp, lk = "", None, None
        stack = [d]
        while stack:
            node = stack.pop()
            items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else []
            for k, v in items:
                if isinstance(v, str) and len(v) > len(longest):
                    longest, lp, lk = v, node, k
                elif isinstance(v, (dict, list)):
                    stack.append(v)
        if lp is None or len(longest) < 40:
            break
        lp[lk] = longest[: len(longest) // 2] + "…"
    return d, True


def get_client() -> GeminiClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = GeminiClient()
    return _CLIENT


def _run(kind: str, payload: dict, subject: str = "", extra_instructions: str = "",
         task_text: str | None = None, system: str = BASE_SYSTEM, max_output_tokens: int = 8192) -> str:
    """Run a one-shot analysis. Large payloads go to Gemini first (large context window); Groq (≈8k tokens/minute on
    the free tier) receives a structurally shrunk payload. Nothing is ever truncated mid-JSON."""
    data = to_jsonable(payload)
    full, _ = shrink_json(data, 120_000)
    head = f"TASK:\n{task_text or TASKS[kind]}\n{extra_instructions}\n\nDATA (JSON, computed by Python"
    client = get_client()
    cfg = client.cfg
    groq_ok = cfg.groq_configured and cfg.ai_provider in ("groq", "auto")
    full_body = json.dumps(full, default=str, separators=(",", ":"))
    small, shrunk = shrink_json(full, GROQ_PAYLOAD_BUDGET)
    small_body = json.dumps(small, default=str, separators=(",", ":"))
    note = ("; lists were shortened to fit the provider's request limit — say so if something seems missing"
            if shrunk else "")
    body = full_body
    if client._client is not None and hasattr(client._client, "models"):        # injected Gemini (tests)
        text = client.generate(f"{head}):\n{full_body}", system=system, max_output_tokens=max_output_tokens)
    elif groq_ok and not shrunk:
        text = client.generate(f"{head}):\n{full_body}", system=system, max_output_tokens=max_output_tokens)
    elif cfg.gemini_configured and cfg.ai_provider != "groq":
        try:
            text = client._generate_gemini(f"{head}):\n{full_body}", system=system,
                                           max_output_tokens=max_output_tokens)
        except GeminiError as e:
            if not groq_ok:
                raise
            log.warning("Gemini failed for large payload (%s); using Groq with a shortened payload", e)
            body = small_body
            text = client._generate_groq(f"{head}{note}):\n{small_body}", system, 0.3, max_output_tokens)
    elif groq_ok:
        body = small_body
        text = client._generate_groq(f"{head}{note}):\n{small_body}", system, 0.3, max_output_tokens)
    else:
        text = client.generate(f"{head}):\n{full_body}", system=system, max_output_tokens=max_output_tokens)
    with session_scope() as s:
        s.add(AIReport(kind=kind, subject=subject[:64], model=client.active_model[:64],
                       input_json=body[:200_000], output_text=text))
    return text


def intel_analysis(kind: str, payload: dict, subject: str = "", **fmt) -> str:
    """Run one of the INTEL_TASKS with the intelligence-desk system prompt."""
    task = INTEL_TASKS[kind].format(**fmt) if fmt else INTEL_TASKS[kind]
    return _run(kind, payload, subject or kind, task_text=task, system=INTEL_SYSTEM, max_output_tokens=16384)


def news_impact(payload: dict) -> str:
    return _run("news_impact", payload, "news")


def test_groq_connection() -> tuple[bool, str]:
    cfg = load_config()
    if not cfg.groq_configured:
        return False, "GROQ_API_KEY is not configured in .env or secrets."
    try:
        import requests
        headers = {"Authorization": f"Bearer {cfg.groq_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": cfg.groq_model or "openai/gpt-oss-120b",
            "messages": [
                {"role": "system", "content": "You are a connectivity check."},
                {"role": "user", "content": "Reply with exactly: OK"}
            ],
            "temperature": 0,
            "max_tokens": 15
        }
        r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=15)
        if r.status_code == 200:
            txt = r.json()["choices"][0]["message"]["content"].strip()
            return True, f"Connected to Groq ({payload['model']}): {txt[:50]}"
        return False, f"Groq HTTP {r.status_code}: {r.text[:150]}"
    except Exception as e:
        return False, f"Groq error: {e}"


def test_gemini_connection() -> tuple[bool, str]:
    cfg = load_config()
    if not cfg.gemini_configured:
        return False, "GEMINI_API_KEY is not configured in .env or secrets."
    try:
        c = get_client()
        txt = c._generate_gemini("Reply with exactly: OK", system="You are a connectivity check.",
                                 temperature=0, max_output_tokens=20)
        return True, f"Connected to Gemini ({c.active_model}): {txt.strip()[:40]}"
    except Exception as e:
        return False, f"Gemini error: {e}"


def test_connection() -> tuple[bool, str]:
    cfg = load_config()
    if cfg.groq_configured and (cfg.ai_provider in ("groq", "auto") or not cfg.gemini_configured):
        return test_groq_connection()
    if cfg.gemini_configured:
        return test_gemini_connection()
    if cfg.groq_configured:
        return test_groq_connection()
    return False, "Neither GROQ_API_KEY nor GEMINI_API_KEY is configured."


def recent_reports(kind: str | None = None, subject: str | None = None, limit: int = 20) -> list[AIReport]:
    from sqlalchemy import select
    with session_scope() as s:
        q = select(AIReport)
        if kind:
            q = q.where(AIReport.kind == kind)
        if subject:
            q = q.where(AIReport.subject == subject)
        return list(s.scalars(q.order_by(AIReport.created_at.desc()).limit(limit)).all())
