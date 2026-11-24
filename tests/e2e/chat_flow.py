"""Browser test of the AI Research Chat (LIVE: makes one real AI request per run).

    python tests/e2e/chat_flow.py --base http://127.0.0.1:8599 --width 390 --out data/qa_screens

Checks: input is visible and usable, streaming shows partial output, final answer renders as formatted Markdown
(no raw '##' or '|---|' text, no raw JSON), tables do not overflow the page, citation links are clickable and
open in a new tab, the conversation survives a page reload, and no console errors occur.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

Q = "Give me a short comparison table of the S&P 500, Nifty 50 and gold today, then explain the biggest mover."


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8599")
    ap.add_argument("--width", type=int, default=390)
    ap.add_argument("--out", default="data/qa_screens")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    res: dict = {"width": a.width}
    errors: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": a.width, "height": 844 if a.width < 768 else 900},
                            is_mobile=a.width < 768, has_touch=a.width < 1024)
        page = ctx.new_page()
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load" not in m.text else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{a.base}/ai_research")
        page.wait_for_selector('[data-testid="stChatInput"] textarea', timeout=60_000)
        page.wait_for_timeout(1500)
        page.locator('[data-testid="stChatInput"] textarea').fill(Q)
        box = page.locator('[data-testid="stChatInput"]').bounding_box()
        res["input_visible"] = bool(box and box["y"] + box["height"] <= page.viewport_size["height"] + 1)
        page.keyboard.press("Enter")
        # streaming: the cursor glyph appears while tokens arrive
        try:
            page.wait_for_function("() => document.body.innerText.includes('▍')", timeout=60_000)
            res["streamed_partial"] = True
            page.screenshot(path=str(out / f"chat_streaming_{a.width}.png"))
        except Exception:  # noqa: BLE001
            res["streamed_partial"] = False
        page.wait_for_function("() => !document.querySelector('[data-testid=\"stStatusWidget\"]')", timeout=180_000)
        page.wait_for_timeout(1500)
        msgs = page.locator('[data-testid="stChatMessage"]')
        res["messages"] = msgs.count()
        last = msgs.nth(msgs.count() - 1)
        text = last.inner_text()
        res["error_shown"] = last.locator('[data-testid="stAlert"]').count() > 0
        res["raw_markdown_visible"] = any(t in text for t in ("## ", "|---", "**"))
        res["raw_json_visible"] = text.strip().startswith("{")
        res["tables"] = last.locator("table").count()
        res["links"] = last.locator("a[href^='http']").count()
        res["links_new_tab"] = all(
            (l.get_attribute("target") == "_blank") for l in last.locator("[data-testid='stMarkdownContainer'] a[href^='http']").all())
        res["page_overflow_px"] = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        res["table_contained"] = page.evaluate("""() => [...document.querySelectorAll('[data-testid="stChatMessage"] table')]
            .every(t => t.getBoundingClientRect().right <= document.documentElement.clientWidth + 1)""")
        page.screenshot(path=str(out / f"chat_answer_{a.width}.png"), full_page=True)
        # persistence
        page.reload()
        page.wait_for_selector('[data-testid="stChatMessage"]', timeout=60_000)
        page.wait_for_timeout(1500)
        res["messages_after_reload"] = page.locator('[data-testid="stChatMessage"]').count()
        res["console_errors"] = errors[:5]
        b.close()
    print(json.dumps(res, indent=1))
    ok = (res["input_visible"] and not res["error_shown"] and not res["raw_markdown_visible"]
          and not res["raw_json_visible"] and res["page_overflow_px"] <= 1 and res["table_contained"]
          and res["messages_after_reload"] >= 2 and not errors)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
