"""Browser audit: visits every page at several viewports, records exceptions, console errors and horizontal overflow.

Usage (app must be running):
    streamlit run app.py --server.port 8599 &
    python tests/e2e/ui_audit.py --base http://127.0.0.1:8599 --out data/qa_screens [--pages a,b] [--widths 375,1440]

Exit code is non-zero when any page shows a Python exception, a console error, or page-level horizontal overflow.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGES = ["daily_briefing", "global_markets", "us_markets", "india_markets", "gold_commodities", "geopolitics",
         "x_intelligence", "live_newsroom", "trends_radar", "economic_calendar", "news_archive", "ai_research",
         "settings_page", "system_health"]
WIDTHS = [360, 375, 390, 430, 768, 1024, 1280, 1440, 1920]
IGNORED_CONSOLE = ("favicon", "youtube", "ytimg", "googlevideo", "doubleclick", "Permissions-Policy",
                   "third-party cookie", "Failed to load resource: net::ERR_BLOCKED_BY_CLIENT", "googleads",
                   "Unrecognized feature", "allow-scripts and allow-same-origin",
                   "Failed to load resource")  # failed requests are tracked via the response listener instead


def audit(base: str, out: Path, pages: list[str], widths: list[int], timeout_s: int) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for w in widths:
            h = 844 if w < 768 else (1024 if w < 1280 else 900)
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1,
                                      is_mobile=w < 768, has_touch=w < 1024)
            for name in pages:
                page = ctx.new_page()
                console: list[str] = []
                page.on("console", lambda m, c=console: c.append(f"{m.type}: {m.text}") if m.type == "error" else None)
                page.on("pageerror", lambda e, c=console: c.append(f"pageerror: {e}"))
                # Streamlit probes <subpath>/_stcore/* before the root path; those 404s are expected.
                page.on("response", lambda r, c=console: c.append(f"http {r.status}: {r.url}")
                        if r.status >= 400 and "/_stcore/" not in r.url and "127.0.0.1" in r.url else None)
                page.goto(f"{base}/" + ("" if name == "daily_briefing" else name), wait_until="domcontentloaded")
                try:
                    page.wait_for_selector('[data-testid="stApp"]', timeout=20_000)
                    # wait until Streamlit finishes running the script
                    # Streamlit shows the status widget (running icon / Stop button) while the script runs.
                    page.wait_for_timeout(800)
                    page.wait_for_function(
                        "() => !document.querySelector('[data-testid=\"stStatusWidget\"]')",
                        timeout=timeout_s * 1000)
                    page.wait_for_timeout(1200)
                except Exception as e:  # noqa: BLE001
                    console.append(f"timeout: {e}")
                exc = page.locator('[data-testid="stException"]').all_inner_texts()
                overflow = page.evaluate("""() => {
                    const de = document.documentElement;
                    const main = document.querySelector('[data-testid="stMain"]') || document.body;
                    const offenders = [];
                    if (de.scrollWidth > de.clientWidth + 1 || main.scrollWidth > main.clientWidth + 1) {
                        document.querySelectorAll('[data-testid="stMain"] *').forEach(el => {
                            const r = el.getBoundingClientRect();
                            if (r.right > de.clientWidth + 2 && r.width > 0 && offenders.length < 6) {
                                offenders.push((el.getAttribute('data-testid') || el.tagName) + ':' +
                                               Math.round(r.right) + ' ' + (el.className || '').toString().slice(0, 40));
                            }
                        });
                    }
                    return {doc: de.scrollWidth - de.clientWidth, main: main.scrollWidth - main.clientWidth,
                            offenders};
                }""")
                errs = [c for c in console if not any(s.lower() in c.lower() for s in IGNORED_CONSOLE)]
                shot = out / f"{name}_{w}.png"
                page.screenshot(path=str(shot), full_page=w in (375, 1440))
                r = {"page": name, "width": w, "exceptions": [e[:300] for e in exc], "console_errors": errs[:5],
                     "overflow_px": max(overflow["doc"], overflow["main"]), "offenders": overflow["offenders"],
                     "screenshot": str(shot)}
                results.append(r)
                flag = "FAIL" if (r["exceptions"] or r["console_errors"] or r["overflow_px"] > 1) else "ok"
                print(f"{flag:4} {w:5} {name:20} exc={len(exc)} console={len(errs)} overflow={r['overflow_px']}"
                      + (f" {r['offenders'][:2]}" if r["offenders"] else "")
                      + (f" {errs[:1]}" if errs else "") + (f" {exc[0][:120]!r}" if exc else ""), flush=True)
                page.close()
            ctx.close()
        browser.close()
    (out / "results.json").write_text(json.dumps(results, indent=1))
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8599")
    ap.add_argument("--out", default="data/qa_screens")
    ap.add_argument("--pages", default=",".join(PAGES))
    ap.add_argument("--widths", default=",".join(map(str, WIDTHS)))
    ap.add_argument("--timeout", type=int, default=90)
    a = ap.parse_args()
    res = audit(a.base, Path(a.out), a.pages.split(","), [int(x) for x in a.widths.split(",")], a.timeout)
    bad = [r for r in res if r["exceptions"] or r["console_errors"] or r["overflow_px"] > 1]
    print(f"\n{len(res) - len(bad)}/{len(res)} page×viewport checks clean")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
