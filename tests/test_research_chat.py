"""AI Research Chat: answer formatting, context selection, persistence, Gemini streaming, X client.

Covers the AI scenarios from the QA brief with deterministic fakes (no network, no API spend):
simple question, detailed US analysis, gold, India, geopolitics, a company, semis/AI, multi-source,
insufficient information, provider failure and rate limits.
"""
from unittest.mock import MagicMock, patch

import pytest

from tradingos.ai import formatting as fmt


# ----------------------------------------------------------------------------- formatting
def test_strip_reasoning_and_unwrap_fence():
    raw = "<think>internal plan</think>```markdown\n## Summary\n- Gold **+1.2%**\n```"
    out, rep = fmt.clean_answer(raw, colour=False)
    assert out.startswith("## Summary") and "think" not in out and "```" not in out and rep["unwrapped_fence"]


def test_malformed_table_is_repaired():
    raw = "Intro text\n| Asset | 1D |\n| Gold | +1.2% |\n| Oil | -0.8% | extra |\nAfter"
    out = fmt.normalize_tables(raw)
    lines = out.split("\n")
    i = lines.index("| Asset | 1D |")
    assert lines[i - 1] == "" and lines[i + 1] == "|---|---|"
    assert "| Oil | -0.8% extra |" in out        # extra cell merged, column count preserved
    assert lines[-2] == "" and lines[-1] == "After"


def test_table_with_separator_kept_and_short_rows_padded():
    out = fmt.normalize_tables("| A | B | C |\n|:--|--:|---|\n| 1 | 2 |")
    assert out.split("\n") == ["| A | B | C |", "|---|---|---|", "| 1 | 2 |  |"]


def test_raw_json_answer_rendered_as_markdown():
    out, rep = fmt.clean_answer('{"summary": "Risk-off", "drivers": ["yields", "dollar"]}', colour=False)
    assert rep.get("json_rendered") and "**Summary:** Risk-off" in out and "- yields" in out and "{" not in out


def test_unverified_links_removed_and_verified_kept():
    allowed = ["https://www.reuters.com/a"]
    text = ("Per [Reuters](https://www.reuters.com/a/) and [Fake](https://made-up.example/x); "
            "see https://other.example/y")
    out, n = fmt.enforce_citations(text, allowed)
    assert "[Reuters](https://www.reuters.com/a/)" in out
    assert "made-up.example" not in out and "other.example" not in out and n == 2


def test_links_in_code_blocks_untouched():
    out, n = fmt.enforce_citations("```\ncurl https://x.example\n```", [])
    assert "https://x.example" in out and n == 0


def test_moves_coloured_but_not_ranges_links_or_code():
    out = fmt.color_moves("Gold +1.20%, Nifty -0.85% and 2-3% range. [x](https://a.com/+5%) `+9%`")
    assert ":green[+1.20%]" in out and ":red[-0.85%]" in out
    assert "2-3%" in out and "https://a.com/+5%" in out and "`+9%`" in out


def test_duplicate_paragraphs_removed():
    p = "The S&P 500 fell 0.6% as Treasury yields rose to 4.9%, pressuring growth stocks broadly."
    out = fmt.dedupe_paragraphs(f"{p}\n\n{p}\n\nNext.")
    assert out.count("S&P 500") == 1 and out.endswith("Next.")


def test_close_partial_for_streaming():
    assert fmt.close_partial("text\n```python\nx = 1").endswith("```")
    assert fmt.close_partial("| A | B |\n|---|---|\n| 1 | 2").split("\n")[-1] == "|---|---|"
    assert "<think>" not in fmt.close_partial("<think>still thinking")


def test_sources_markdown_only_cited():
    src = [{"title": "A [x]", "source": "Reuters", "url": "https://a", "published": "24 Nov"},
           {"title": "B", "source": "FT", "url": "https://b"}]
    md = fmt.sources_markdown(src, cited_only_urls=["https://a"])
    assert md == "1. [A (x)](https://a) — Reuters · 24 Nov"


# ----------------------------------------------------------------------------- context selection
PAYLOAD = {
    "edition": {"generated_at_utc": "2026-11-25 06:00 UTC"},
    "risk_appetite": {"label": "Mixed"},
    "markets": {k: [{"Name": k, "Last": 1.0, "1D %": 0.5}] for k in (
        "us_indices", "volatility", "us_yields", "credit_bonds", "currencies", "europe", "asia_pacific", "india",
        "precious_metals", "energy_industrial", "magnificent_7", "us_sectors_by_1w", "us_themes_by_1w",
        "india_sectors_by_1w")},
    "gold": {"gold": {"Last": 3559.9}, "drivers_1y": [1], "drivers_1m": [{"Driver": "DXY", "Change": "+1.98%"}]},
    "geopolitics": [{"theater": "US–China", "top_events": [{"headline": "Export curbs", "url": "https://geo/1",
                                                             "source": "Reuters", "when_utc": "24 Nov"}]}],
    "trends_radar": [{"Theme": "AI semis", "Stage": "Established", "Evidence": "long"}],
    "economic_calendar": [{"event": "CPI", "importance": "high"}, {"event": "Minor", "importance": "low"}],
    "central_banks": [{"bank": "RBI", "latest_communications": [{"headline": "Policy", "url": "https://rbi/1",
                                                                  "published_utc": "2026-11-24"}]}],
    "news_ranked": [
        {"tier": "MUST KNOW", "headline": "Gold jumps as dollar slides", "source": "Reuters", "url": "https://n/gold",
         "published_utc": "2026-11-24 10:00", "category": "commodities", "region": "Global", "topics": "Gold & metals"},
        {"tier": "IMPORTANT", "headline": "Nifty closes lower on IT selling", "source": "ET", "url": "https://n/nifty",
         "published_utc": "2026-11-24 10:30", "category": "markets", "region": "India", "topics": "India markets"},
        {"tier": "INTERESTING", "headline": "Nvidia supplier TSMC lifts capex", "source": "FT", "url": "https://n/tsmc",
         "published_utc": "2026-11-24 09:00", "category": "technology", "region": "Asia",
         "topics": "AI & semiconductors"},
        {"tier": "IGNORE FOR NOW", "headline": "Routine notice", "source": "X", "url": "https://n/ignore",
         "category": "markets", "region": "US"},
    ],
}


@pytest.mark.parametrize("q,intent,market_key", [
    ("Why are gold prices moving?", "gold", "precious_metals"),
    ("How is the Indian market doing today?", "india", "india"),
    ("Give me a detailed US market analysis", "us", "us_indices"),
    ("What are the geopolitical risks from China tariffs?", "geo", "energy_industrial"),
    ("Semiconductor and AI industry trends?", "tech", "us_themes_by_1w"),
])
def test_intent_routing(q, intent, market_key):
    from tradingos.intel import research
    ctx, sources = research.select_context(PAYLOAD, q)
    assert intent in ctx["detected_topics"] and market_key in ctx["markets"]
    assert all(n["tier"] != "IGNORE FOR NOW" for n in ctx["news"])
    urls = {s["url"] for s in sources}
    assert {n["url"] for n in ctx["news"]} <= urls          # every news URL is a citable source


def test_most_relevant_news_first_and_specific_sections():
    from tradingos.intel import research
    ctx, _ = research.select_context(PAYLOAD, "Why is gold moving?")
    assert ctx["news"][0]["url"] == "https://n/gold" and "gold_drivers" in ctx and "drivers_1y" not in ctx["gold_drivers"]
    assert "transmission_framework" not in str(ctx.get("geopolitics_theaters"))   # only for geopolitics questions
    ctx, src = research.select_context(PAYLOAD, "What did the RBI say about inflation in India?")
    assert ctx["news"][0]["url"] == "https://n/nifty" and "https://rbi/1" in {s["url"] for s in src}
    assert all(e["importance"] != "low" for e in ctx["economic_calendar"])
    ctx, _ = research.select_context(PAYLOAD, "AI chips outlook")
    assert "Evidence" not in ctx["trends_radar"][0]


def test_simple_question_gets_general_context():
    from tradingos.intel import research
    ctx, _ = research.select_context(PAYLOAD, "hello?")
    assert ctx["detected_topics"] == ["general"] and "us_indices" in ctx["markets"] and "india" in ctx["markets"]


def test_ticker_extraction():
    from tradingos.intel import research
    assert research.extract_tickers("What's the latest on Nvidia and $AAPL?") == ["AAPL", "NVDA"]
    assert research.extract_tickers("Is AI driving US GDP?") == []
    assert "MSFT" in research.extract_tickers("compare MSFT")


def test_company_brief_and_sources(fake_provider, uptrend):
    from tradingos import services
    from tradingos.intel import research
    from tradingos.settings import AppSettings
    fake_provider({"SPY": uptrend, "NVDA": uptrend})
    ctx = services.stock_context("NVDA", AppSettings(), with_fundamentals=False)
    ctx["news"] = [{"headline": "Nvidia beats", "source": "CNBC", "url": "https://c/nv", "published_utc": "2026-11-24"}]
    brief = research.company_brief(ctx)
    assert brief["ticker"] == "NVDA" and brief["price_snapshot_daily"]["close"] > 0 and "supports" not in str(brief)
    c, src = research.select_context(PAYLOAD, "What's the latest on Nvidia?", [brief])
    assert c["companies"][0]["ticker"] == "NVDA" and "https://c/nv" in {s["url"] for s in src}
    missing = research.company_brief({"ticker": "ZZZZ", "error": "No price data for ZZZZ."})
    assert missing == {"ticker": "ZZZZ", "error": "No price data for ZZZZ."}   # insufficient data is explicit


def test_fingerprint_stable_across_time_but_not_questions():
    from tradingos.intel import research
    a, _ = research.select_context(PAYLOAD, "gold?")
    b = dict(a, question_received_utc="later")
    assert research.context_fingerprint(a, "gold?", []) == research.context_fingerprint(b, "Gold? ", [])
    assert research.context_fingerprint(a, "gold?", []) != research.context_fingerprint(a, "oil?", [])


def test_research_prompt_has_grounding_and_format_rules():
    from tradingos.ai.gemini import RESEARCH_SYSTEM
    for phrase in ("Never invent", "Not in today's data", "AI view", "Never write URLs", "[N3]",
                   "Executive Summary", "Never output JSON", "header row"):
        assert phrase in RESEARCH_SYSTEM


# ----------------------------------------------------------------------------- persistence
def test_chat_store_roundtrip():
    from tradingos.intel import chat_store
    c = chat_store.new_conversation()
    chat_store.add(c, "user", "Why is gold up?")
    chat_store.add(c, "assistant", "Because…", model="groq/x", sources=[{"url": "https://a", "title": "t"}])
    chat_store.add(c, "error", "AI service unavailable")
    h = chat_store.history(c)
    assert [m["role"] for m in h] == ["user", "assistant", "error"] and h[1]["sources"][0]["url"] == "https://a"
    convs = chat_store.conversations()
    assert convs[0]["conversation"] == c and convs[0]["title"] == "Why is gold up?" and convs[0]["messages"] == 3
    with pytest.raises(ValueError):
        chat_store.add(c, "system", "x")
    assert chat_store.delete_conversation(c) == 3 and chat_store.history(c) == []


# ----------------------------------------------------------------------------- Gemini streaming
class _Chunk:
    def __init__(self, t):
        self.text = t


def _gemini_client(monkeypatch, behaviour):
    from google.genai import errors

    from tradingos.ai import gemini
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("GEMINI_MIN_INTERVAL_SECONDS", "0")
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = []

    class Models:
        def generate_content_stream(self, model, contents, config):
            calls.append(model)
            b = behaviour.get(model, "ok")
            if b == "daily":
                raise errors.ClientError(429, {"error": {"code": 429, "message": "per day limit. Please retry in 5h0m0s."}})
            if b == "midfail":
                def gen():
                    yield _Chunk("half ")
                    raise errors.ServerError(503, {"error": {"code": 503, "message": "overloaded"}})
                return gen()
            return iter([_Chunk("## Answer\n"), _Chunk(f"from {model}")])

    c = gemini.GeminiClient()
    c._client = type("C", (), {"models": Models()})()
    return c, calls


def test_gemini_stream_falls_back_on_daily_quota(monkeypatch):
    c, calls = _gemini_client(monkeypatch, {"gemini-3.8-flash": "daily"})
    out = c.chat([], "q")
    assert out == "## Answer\nfrom gemini-3.7-flash" and calls[:2] == ["gemini-3.8-flash", "gemini-3.7-flash"]
    from tradingos.ai.gemini import quota_status
    assert quota_status()[0]["model"] == "gemini-3.8-flash"


def test_gemini_stream_mid_answer_failure_is_an_error(monkeypatch):
    from tradingos.ai import gemini
    c, _ = _gemini_client(monkeypatch, {"gemini-3.8-flash": "midfail"})
    with pytest.raises(gemini.GeminiError, match="interrupted"):
        c.chat([], "q")


# ----------------------------------------------------------------------------- X client
def test_x_not_configured_is_explicit():
    from tradingos.intel import xintel
    r = xintel.fetch_list({"key": "a", "title": "A", "query": "from:x"})
    assert not r.ok and "not configured" in r.error and r.posts == []
    assert "not configured" in xintel.briefing_section()["status"]


def test_x_fetch_parses_caches_and_budgets(monkeypatch):
    from tradingos.intel import xintel
    monkeypatch.setenv("X_BEARER_TOKEN", "t")
    monkeypatch.setenv("X_DAILY_REQUEST_LIMIT", "1")
    body = {"data": [{"id": "9", "text": "Rates unchanged", "author_id": "1", "created_at": "2026-11-24T14:00:00Z",
                      "public_metrics": {"like_count": 5, "retweet_count": 2, "reply_count": 1}}],
            "includes": {"users": [{"id": "1", "username": "federalreserve", "name": "Federal Reserve", "verified": True}]}}
    item = {"key": "cb", "title": "CB", "query": "from:federalreserve"}
    monkeypatch.setattr(xintel, "load_lists", lambda *a: [item])
    with patch("requests.get", return_value=MagicMock(status_code=200, json=lambda: body)) as get:
        r = xintel.fetch_list(item)
        assert r.ok and r.posts[0]["url"] == "https://x.com/federalreserve/status/9" and r.posts[0]["likes"] == 5
        assert get.call_args[1]["headers"]["Authorization"] == "Bearer t"
        r2 = xintel.fetch_list(item)                       # cached → no second request
        assert r2.from_cache and get.call_count == 1
        r3 = xintel.fetch_list(item, force=True)           # budget of 1 exhausted → cached result + message
        assert get.call_count == 1 and "budget" in r3.error and r3.posts
    sec = xintel.briefing_section()
    assert sec["lists"][0]["posts"][0]["handle"] == "federalreserve"


@pytest.mark.parametrize("code,needle", [(401, "bearer token"), (402, "plan or credit"), (429, "rate limit")])
def test_x_errors_are_explained(monkeypatch, code, needle):
    from tradingos.intel import xintel
    monkeypatch.setenv("X_BEARER_TOKEN", "t")
    with patch("requests.get", return_value=MagicMock(status_code=code, headers={})):
        r = xintel.fetch_list({"key": f"k{code}", "title": "T", "query": "q"})
    assert needle in r.error and r.posts == []


def test_live_channel_config_is_valid():
    import json
    import re

    from tradingos.config import PROJECT_ROOT
    chans = json.loads((PROJECT_ROOT / "config" / "live_channels.json").read_text())["channels"]
    assert len(chans) >= 6 and all(re.fullmatch(r"UC[\w-]{22}", c["channel_id"]) for c in chans)
    assert len({c["channel_id"] for c in chans}) == len(chans)


def test_fit_context_respects_budget_and_filters_sources():
    from tradingos.intel import research
    big = dict(PAYLOAD)
    big["news_ranked"] = [dict(PAYLOAD["news_ranked"][0], url=f"https://n/{i}", headline=f"Gold story {i}",
                               summary="s" * 400) for i in range(40)]
    big["markets"] = {k: [{"Name": f"{k}{i}", "Last": 1.0, "1D %": 0.1} for i in range(20)] for k in PAYLOAD["markets"]}
    ctx, src = research.select_context(big, "Why is gold moving?", max_news=30)
    fitted, fsrc = research.fit_context(ctx, src, max_chars=6000)
    assert research._size(fitted) <= 6000 and fitted["context_trimmed"]
    kept = {n["url"] for n in fitted["news"]}
    assert {s["url"] for s in fsrc if s["url"].startswith("https://n/")} == kept   # sources match what was sent
    small, ssrc = research.fit_context(*research.select_context(PAYLOAD, "gold?"), max_chars=50_000)
    assert not small["context_trimmed"]


def test_citation_ids_become_verified_links():
    src = [{"id": "N3", "source": "Reuters (via Finnhub)", "url": "https://r/3"},
           {"id": "N1", "source": "FT", "url": "https://f/1"}]
    out, rep = fmt.clean_answer("Gold fell 2.6% [N3]. See 【N1】, [N1, N3]; 【data_generated】 [N9] done.",
                                sources=src, allowed_urls=[s["url"] for s in src])
    assert "[Reuters](https://r/3)" in out and "[FT](https://f/1)" in out
    assert "N9" not in out and "【" not in out and "data_generated" not in out
    assert rep["cited_urls"] == ["https://f/1", "https://r/3"]


def test_unicode_minus_and_narrow_spaces_normalised_and_coloured():
    out, _ = fmt.clean_answer("Nasdaq −2.06 % and gold ‑1.5 % vs +0.4 %")
    assert ":red[-2.06%]" in out and ":red[-1.5%]" in out and ":green[+0.4%]" in out


def test_context_items_carry_citation_ids():
    from tradingos.intel import research
    ctx, src = research.select_context(PAYLOAD, "What are the geopolitical risks and what did the RBI say?")
    assert all(n["id"].startswith("N") for n in ctx["news"])
    assert {s["id"][0] for s in src} >= {"N", "G", "B"}
    assert PAYLOAD["geopolitics"][0]["top_events"][0].get("id") is None   # payload itself not mutated


def test_gold_driver_window_is_explicit_and_floats_rounded():
    from tradingos.intel import research
    p = dict(PAYLOAD, markets={"precious_metals": [{"Name": "Gold", "1D %": -2.6346046378}]})
    ctx, _ = research.select_context(p, "why is gold down")
    assert ctx["gold_drivers"]["drivers_1m"][0] == {"Driver": "DXY", "Change over last 1 month": "+1.98%"}
    assert ctx["markets"]["precious_metals"][0]["1D %"] == -2.63


def test_citation_variants_and_g7_untouched():
    src = [{"id": "N2", "source": "ET", "url": "https://e/2"}, {"id": "N4", "source": "CNBC", "url": "https://c/4"},
           {"id": "G1", "source": "Reuters", "url": "https://g/1"}]
    out, rep = fmt.clean_answer("A (N2). B (Economic Times, N4). C N2 again. G7 and G20 met (G1). N99 stays.",
                                sources=src, colour=False)
    assert out.count("[ET](https://e/2)") == 2 and "[CNBC](https://c/4)" in out and "[Reuters](https://g/1)" in out
    assert "G7" in out and "G20" in out and "N99" in out and "Economic Times," not in out


def test_thousands_nbsp_and_en_dash_minus():
    out = fmt.normalize_unicode("S&P 7 196.87 | –0.56% | 2020–2024 range | 1 234 567")
    assert "7,196.87" in out and "| -0.56% |" in out and "2020–2024" in out and "1,234,567" in out


def test_shrink_json_keeps_valid_structure_and_head_of_lists():
    import json as _j

    from tradingos.ai.gemini import shrink_json
    data = {"news": [{"h": f"story {i}", "s": "x" * 200} for i in range(100)], "markets": {"a": list(range(500))},
            "note": "keep"}
    small, shrunk = shrink_json(data, 4000)
    assert shrunk and len(_j.dumps(small, separators=(",", ":"))) <= 4000
    assert small["note"] == "keep" and small["news"][0]["h"] == "story 0"
    same, s2 = shrink_json({"a": 1}, 100)
    assert same == {"a": 1} and not s2


def test_large_payload_prefers_gemini_and_groq_gets_shrunk(monkeypatch):
    from tradingos.ai import gemini
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    calls = []
    c = gemini.GeminiClient()
    monkeypatch.setattr(gemini, "_CLIENT", c)

    def fake_gemini(prompt, system=None, temperature=0.3, max_output_tokens=8192):
        calls.append(("gemini", len(prompt)))
        raise gemini.GeminiError("quota")

    def fake_groq(prompt, system, temperature, max_output_tokens):
        calls.append(("groq", len(prompt)))
        return "ok"
    monkeypatch.setattr(c, "_generate_gemini", fake_gemini)
    monkeypatch.setattr(c, "_generate_groq", fake_groq)
    big = {"rows": [{"t": "y" * 300} for _ in range(300)]}
    assert gemini._run("news_impact", big) == "ok"
    assert [k for k, _ in calls] == ["gemini", "groq"] and calls[1][1] < gemini.GROQ_PAYLOAD_BUDGET + 2000
    calls.clear()
    assert gemini._run("news_impact", {"rows": [1, 2]}) == "ok"             # small payload → Groq directly
    assert [k for k, _ in calls] == ["groq"]


def test_duplicate_urls_keep_all_ids_as_aliases():
    """Regression: a geopolitics event with the same URL as a news item must still resolve when cited by its G id."""
    from tradingos.intel import research
    p = dict(PAYLOAD)
    p["geopolitics"] = [{"theater": "Gold", "top_events": [{"headline": "Gold jumps", "url": "https://n/gold",
                                                             "source": "Reuters", "when_utc": "24 Nov"}]}]
    ctx, src = research.select_context(p, "geopolitical risk for gold")
    gold = [s for s in src if s["url"] == "https://n/gold"]
    assert len(gold) == 1 and "G1" in [gold[0]["id"], *gold[0].get("aliases", [])]
    out, rep = fmt.clean_answer("Gold rose [G1].", sources=src, colour=False)
    assert "[Reuters](https://n/gold)" in out
    _, fsrc = research.fit_context(ctx, src)
    assert any(s["url"] == "https://n/gold" for s in fsrc)


def test_story_card_blocks_unsafe_url_schemes_and_escapes_html():
    from tradingos.ui import intel_ui as iu
    card = iu.story_card({"tier": "MUST KNOW", "headline": "<script>x</script>", "url": "javascript:alert(1)",
                          "source": "Feed", "published_utc": None, "info_type": "Reported", "summary": "<b>s</b>"})
    assert "javascript:" not in card and 'href="#"' in card and "<script>" not in card and "&lt;b&gt;" in card
