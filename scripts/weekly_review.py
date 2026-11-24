"""Weekly (or monthly) trading review → markdown report (+ optional Gemini review).

Usage: python scripts/weekly_review.py [--days 7] [--ai]
"""
import argparse
import json
from datetime import datetime, timedelta

import _bootstrap  # noqa: F401

from tradingos.ai.gemini import to_jsonable
from tradingos.config import load_config
from tradingos.journal.service import trades_dataframe
from tradingos.performance.metrics import period_review
from tradingos.settings import load_settings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--ai", action="store_true")
    a = ap.parse_args()
    cfg, app = load_settings(), load_config()
    end = datetime.now()
    rev = period_review(trades_dataframe(), end - timedelta(days=a.days), end, cfg)
    text = f"# Trading review {rev['period']}\n\n```json\n{json.dumps(to_jsonable(rev), indent=2, default=str)}\n```\n"
    if a.ai and app.gemini_configured:
        from tradingos.ai import gemini
        try:
            text += "\n## Gemini review\n\n" + gemini.weekly_performance_review(rev)
        except gemini.GeminiError as e:
            text += f"\n> AI review failed: {e}\n"
    p = app.reports_dir / f"review-{a.days}d-{end:%Y%m%d}.md"
    p.write_text(text)
    print(f"written {p}")


if __name__ == "__main__":
    main()
