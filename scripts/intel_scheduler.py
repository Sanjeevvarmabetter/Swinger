"""Generate intelligence briefings that are due (idempotent — safe to run every 15 minutes).

Usage:
  python scripts/intel_scheduler.py                 # generate any edition due now (within its 3h grace window)
  python scripts/intel_scheduler.py --list          # show the schedule and next runs (IST)
  python scripts/intel_scheduler.py --edition global_morning [--no-ai]   # generate one edition now

cron (every 15 min):
  */15 * * * * cd /path/to/Swinger && .venv/bin/python scripts/intel_scheduler.py >> data/reports/scheduler.log 2>&1
"""
import argparse
import logging
from datetime import datetime, timezone

import _bootstrap  # noqa: F401

from tradingos.config import load_config
from tradingos.db.session import trading_engine
from tradingos.intel import briefing as br


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--edition", choices=list(br.EDITIONS), help="generate this edition now")
    ap.add_argument("--no-ai", action="store_true", help="facts-only edition (skip Gemini)")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    trading_engine()
    now = datetime.now(timezone.utc)
    if args.list:
        for r in br.next_runs(now):
            print(f"{r['at_ist']:<24} {r['title']}")
        return
    todo = [args.edition] if args.edition else br.due_editions(now)
    if not todo:
        print(f"{now:%Y-%m-%d %H:%M} UTC — nothing due")
        return
    for key in todo:
        b = br.generate(key, use_ai=not args.no_ai)
        out = load_config().reports_dir / f"{key}-{b.edition_date}.md"
        out.write_text((b.ai_md + "\n\n---\n\n" if b.ai_md else "") + b.deterministic_md)
        print(f"{key}: saved briefing #{b.id} → {out}" + (f" (AI failed: {b.ai_error})" if b.ai_error else ""))


if __name__ == "__main__":
    main()
