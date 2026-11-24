"""Daily market briefing: refresh news, run the scanner, write a markdown report.

Usage:  python scripts/daily_briefing.py [--ai] [--no-scan]
Schedule (macOS cron example, 8:00 PM IST ≈ before US open, Mon–Fri):
  0 20 * * 1-5 cd /path/to/Swinger && .venv/bin/python scripts/daily_briefing.py --ai >> data/reports/cron.log 2>&1
"""
import argparse
from datetime import datetime

import _bootstrap  # noqa: F401

from tradingos import briefing, watchlist
from tradingos.config import load_config
from tradingos.data.news import refresh_news
from tradingos.journal.service import trades_dataframe
from tradingos.services import market_context
from tradingos.settings import load_settings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ai", action="store_true", help="append a Gemini interpretation (needs GEMINI_API_KEY)")
    ap.add_argument("--no-scan", action="store_true")
    args = ap.parse_args()
    cfg, app = load_settings(), load_config()
    tickers = [w.ticker for w in watchlist.items()]
    ot = trades_dataframe("OPEN")
    tickers += list(ot["ticker"]) if len(ot) else []
    st = refresh_news(list(dict.fromkeys(tickers))[:25], cfg.news_max_age_days)
    print(f"news: stored {st['stored']} new, {len(st['errors'])} errors")
    if not args.no_scan:
        from tradingos.analysis.scanner import run_scan
        out = run_scan(cfg)
        print(f"scan: {len(out.candidates)} candidates (data as of {out.data.as_of})")
    mc = market_context(cfg)
    report = briefing.deterministic_report(mc)
    if args.ai:
        if not app.gemini_configured:
            report += "\n\n> Gemini not configured — AI section skipped."
        else:
            from tradingos.ai import gemini
            try:
                report += "\n\n---\n# AI interpretation (Gemini)\n\n" + gemini.market_analysis(briefing.ai_payload(mc))
            except gemini.GeminiError as e:
                report += f"\n\n> AI section failed: {e}"
    path = app.reports_dir / f"brief-{datetime.now():%Y%m%d-%H%M}.md"
    path.write_text(report)
    print(f"report written: {path}")


if __name__ == "__main__":
    main()
