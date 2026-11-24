"""LIVE AI evaluation (uses real API calls — not part of the pytest suite).

Runs the QA scenarios through the same pipeline as the AI Research Chat page:
build briefing payload → select context → provider stream → clean_answer → checks.

    .venv/bin/python tests/live/ai_eval.py --out data/qa_ai [--only 1,3]

Each answer is saved as Markdown with an automatic check report. Checks are mechanical (no raw JSON, no code-fenced
answer, tables well-formed, every link in the allowed source set, refusal on missing data); human review of the
saved answers is still needed for analytical quality.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SCENARIOS = [
    (1, "simple", "Is the S&P 500 up or down today?"),
    (2, "us_detailed", "Give me a detailed US market analysis."),
    (3, "gold", "Why are gold prices moving?"),
    (4, "india", "How are Indian markets performing?"),
    (5, "geopolitics", "What are the main geopolitical developments that matter for markets right now?"),
    (6, "company", "What's the latest on Nvidia?"),
    (7, "semis_ai", "What are the current trends in the semiconductor and AI industry?"),
    (8, "multi_source", "Compare how US, Indian and European markets reacted this week and what explains the differences."),
    (9, "insufficient", "What is the consensus forecast for next month's US CPI and what will Apple's Q3 2027 EPS be?"),
]


def check(text: str, allowed: set[str], scenario: str) -> dict:
    from tradingos.ai import formatting as fmt
    links = fmt.cited_urls(text)
    lines = text.split("\n")
    tables_ok = True
    for i, ln in enumerate(lines):
        if ln.strip().startswith("|") and (i == 0 or not lines[i - 1].strip().startswith("|")):
            if i + 1 >= len(lines) or not re.match(r"^\|(\s*:?-+:?\s*\|)+$", lines[i + 1].strip()):
                tables_ok = False
    res = {
        "chars": len(text),
        "no_raw_json": not text.strip().startswith(("{", "[")),
        "not_fenced": not text.strip().startswith("```"),
        "tables_well_formed": tables_ok,
        "links": len(links),
        "all_links_allowed": all(u.rstrip("/").lower() in {a.rstrip("/").lower() for a in allowed} for u in links),
        "has_headings": "## " in text,
        "has_ai_view_label": "AI view" in text,
    }
    if scenario == "insufficient":
        res["states_missing_data"] = bool(re.search(r"not in today['’]?s data|not available|not (?:in|part of) the (?:supplied|provided)", text, re.I))
    if scenario == "simple":
        res["concise"] = len(text) < 1800
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/qa_ai")
    ap.add_argument("--only", default="")
    ap.add_argument("--pause", type=float, default=8.0, help="seconds between calls (provider rate limits)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    from tradingos.ai import formatting as fmt
    from tradingos.ai import gemini
    from tradingos.intel import briefing as br
    from tradingos.intel import research
    from tradingos.services import stock_context
    from tradingos.settings import load_settings

    t0 = time.time()
    payload = br.ai_payload(br.build_payload("global_morning"), max_stories=60)
    print(f"payload built in {time.time() - t0:.0f}s; {len(payload.get('news_ranked', []))} stories")
    only = {int(x) for x in a.only.split(",") if x}
    summary = []
    client = gemini.get_client()
    for n, name, q in SCENARIOS:
        if only and n not in only:
            continue
        companies = [research.company_brief(stock_context(t, load_settings())) for t in research.extract_tickers(q)]
        ctx, sources = research.select_context(payload, q, companies)
        ctx, sources = research.fit_context(ctx, sources)
        size = len(json.dumps(gemini.to_jsonable(ctx), default=str))
        t1 = time.time()
        first = None
        buf = ""
        try:
            for piece in client.chat_stream([], q, ctx):
                if first is None:
                    first = time.time() - t1
                buf += piece
            text, report = fmt.clean_answer(buf, allowed_urls=[s["url"] for s in sources], sources=sources)
            (out / f"{n:02d}_{name}.raw.txt").write_text(buf, encoding="utf-8")
            res = {"ok": True, **check(text, {s["url"] for s in sources}, name), "clean_report": report}
        except gemini.GeminiError as e:
            text, res = f"ERROR: {e}", {"ok": False, "error": str(e)[:300]}
        res.update({"n": n, "scenario": name, "question": q, "model": client.active_model, "context_chars": size,
                    "first_token_s": round(first, 1) if first else None, "total_s": round(time.time() - t1, 1),
                    "sources_supplied": len(sources), "tickers": [c.get("ticker") for c in companies]})
        (out / f"{n:02d}_{name}.md").write_text(f"# Q: {q}\n\n{text}\n\n---\n```json\n{json.dumps(res, indent=1)}\n```\n")
        summary.append(res)
        print(json.dumps({k: v for k, v in res.items() if k not in ("question", "clean_report")}))
        time.sleep(a.pause)
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    return 0 if all(r["ok"] for r in summary) else 1


if __name__ == "__main__":
    sys.exit(main())
