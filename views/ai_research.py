"""AI Research Chat — grounded questions and answers over today's market data, news and calendars."""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

import streamlit as st

from tradingos.ai import formatting as fmt
from tradingos.ai import gemini
from tradingos.config import load_config
from tradingos.data import cache
from tradingos.intel import chat_store, research
from tradingos.ui import components as ui
from tradingos.ui.state import stock_ctx

ANSWER_CACHE_TTL = 30 * 60
SUGGESTIONS = [
    "What moved global markets today?",
    "Give me a detailed US market analysis",
    "Why is gold moving?",
    "How are Indian markets doing?",
    "What are the main geopolitical risks for markets right now?",
    "What's the latest on Nvidia?",
    "What are the trends in semiconductors and AI?",
]


@st.cache_data(ttl=900, show_spinner=False)
def _payload(nonce: int) -> dict:  # noqa: ARG001
    from tradingos.intel import briefing as br
    return br.ai_payload(br.build_payload("global_morning"), max_stories=60)


def _render_message(m: dict) -> None:
    if m["role"] == "user":
        with st.chat_message("user"):
            st.markdown(m["text"])
        return
    with st.chat_message("assistant"):
        if m["role"] == "error":
            st.error(m["text"], icon=":material/error:")
            return
        st.markdown(m["text"])
        _render_footer(m["text"], m.get("sources", []), m.get("model", ""),
                       m["created_at"].strftime("%d %b %H:%M UTC") if m.get("created_at") else "")


def _render_footer(text: str, sources: list[dict], model: str, when: str, note: str = "") -> None:
    cited = {s["url"] for s in sources} & set(fmt.cited_urls(text))
    cited_list = [s for s in sources if s["url"] in cited]
    if cited_list:
        st.markdown('<div class="sources-box"><b>Sources cited</b></div>', unsafe_allow_html=True)
        st.markdown(fmt.sources_markdown(cited_list))
    if sources and len(sources) > len(cited_list):
        with st.expander(f"All data sources supplied to the AI ({len(sources)} items)"):
            st.markdown(fmt.sources_markdown(sources))
    st.markdown(f'<div class="msg-meta">{model or "AI"} · {when}{(" · " + note) if note else ""} · AI interpretation '
                "of the app's data — statements marked “AI view” are not sourced facts. Not financial advice.</div>",
                unsafe_allow_html=True)


ui.render_top_bar(show_refresh=False)
ui.page_header("AI Research Chat",
               "Ask about markets, gold, India, geopolitics, macro or a company. Answers use only the data in this app "
               "(delayed market data, ranked news, calendars); links are checked against the sources supplied.")

cfg = load_config()
# The conversation id lives in the URL (?c=…) so a page refresh or a bookmarked link reopens the same conversation.
_qc = st.query_params.get("c", "")
if "chat_conv" not in st.session_state:
    st.session_state["chat_conv"] = _qc if re.fullmatch(r"[0-9a-f]{16}", _qc or "") else chat_store.new_conversation()
conv = st.session_state["chat_conv"]
if _qc != conv:
    st.query_params["c"] = conv

with st.container(horizontal=True, gap="small", vertical_alignment="center"):
    if st.button("New chat", icon=":material/add_comment:", key="chat_new"):
        st.session_state["chat_conv"] = chat_store.new_conversation()
        st.rerun()
    with st.popover("History", icon=":material/history:"):
        convs = chat_store.conversations(25)
        if not convs:
            st.caption("No saved conversations yet.")
        for c in convs:
            label = f"{c['title']}  ·  {c['last']:%d %b %H:%M}"
            if st.button(label, key=f"conv_{c['conversation']}", width="stretch",
                         type="primary" if c["conversation"] == conv else "secondary"):
                st.session_state["chat_conv"] = c["conversation"]
                st.rerun()
    st.caption(f"Engine: {ui.ai_engine_label()}")

if not cfg.ai_configured:
    st.warning("AI is not configured. Add GROQ_API_KEY or GEMINI_API_KEY to your .env file (or Streamlit secrets) and "
               "restart. All market pages work without it.", icon=":material/key_off:")

hist = chat_store.history(conv)

if not hist:
    st.markdown('<div class="sec-title">Try asking</div>', unsafe_allow_html=True)
    with st.container(horizontal=True, gap="small", key="chat_suggest"):
        for i, s in enumerate(SUGGESTIONS):
            if st.button(s, key=f"sugg_{i}", disabled=not cfg.ai_configured):
                st.session_state["_chat_pending"] = s
                st.rerun()

for m in hist:
    _render_message(m)

prompt = st.chat_input("Ask a research question…", disabled=not cfg.ai_configured, max_chars=2000, key="chat_box")
question = (prompt or st.session_state.pop("_chat_pending", None) or "").strip()

if question:
    chat_store.add(conv, "user", question)
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        status = st.empty()
        status.markdown('<div class="msg-meta">Gathering today\'s market data and news…</div>', unsafe_allow_html=True)
        try:
            payload = _payload(st.session_state.get("mkt_nonce", 0) + st.session_state.get("news_nonce", 0))
            companies = []
            for t in research.extract_tickers(question):
                companies.append(research.company_brief(stock_ctx(t)))
            context, sources = research.select_context(payload, question, companies)
            context, sources = research.fit_context(context, sources)
        except Exception as e:  # noqa: BLE001
            status.empty()
            msg = f"Could not assemble market data for this question ({type(e).__name__}: {str(e)[:160]}). Try again."
            st.error(msg, icon=":material/error:")
            chat_store.add(conv, "error", msg)
            st.stop()

        allowed = [s["url"] for s in sources]
        prior = [m for m in hist if m["role"] in ("user", "assistant")]
        key = "chat|answer|" + research.context_fingerprint(context, question, prior)
        cached = cache.get(key, ANSWER_CACHE_TTL)
        note = ""
        if cached:
            text, model = cached["text"], cached["model"]
            note = f"reused answer from {cached['at']} (same question, same data)"
            status.markdown(text)
        else:
            client = gemini.get_client()
            buf, last = "", 0.0
            status.markdown('<div class="msg-meta">Analysing…</div>', unsafe_allow_html=True)
            try:
                for piece in client.chat_stream(prior, question, context):
                    buf += piece
                    if time.time() - last > 0.12:
                        status.markdown(fmt.close_partial(buf, sources) + " ▍")
                        last = time.time()
            except gemini.GeminiError as e:
                status.empty()
                msg = f"AI service unavailable: {e}"
                if buf:
                    msg = f"The answer was cut off and has been discarded. {e}"
                st.error(msg, icon=":material/error:")
                chat_store.add(conv, "error", msg)
                st.stop()
            except Exception as e:  # noqa: BLE001
                status.empty()
                msg = f"AI request failed ({type(e).__name__}). Please retry."
                st.error(msg, icon=":material/error:")
                chat_store.add(conv, "error", msg)
                st.stop()
            text, report = fmt.clean_answer(buf, allowed_urls=allowed, sources=sources)
            if not text:
                status.empty()
                msg = "The AI returned an empty answer. Please rephrase or retry."
                st.error(msg, icon=":material/error:")
                chat_store.add(conv, "error", msg)
                st.stop()
            if report.get("links_removed"):
                note = f"{report['links_removed']} unverified link(s) removed"
            model = client.active_model
            status.markdown(text)
            cache.put(key, {"text": text, "model": model, "at": datetime.now(timezone.utc).strftime("%H:%M UTC")})
            try:
                from tradingos.db.models import AIReport
                from tradingos.db.session import session_scope
                with session_scope() as s:
                    s.add(AIReport(kind="research_chat", subject=question[:64], model=model[:64],
                                   input_json=str(context)[:200_000], output_text=text))
            except Exception:  # noqa: BLE001 — audit log must never break the chat
                pass
        _render_footer(text, sources, model, datetime.now(timezone.utc).strftime("%d %b %H:%M UTC"), note)
        chat_store.add(conv, "assistant", text, model=model, sources=sources)
