"""Check watchlist price alerts and open-trade stop/target proximity on the latest close.

Usage: python scripts/check_alerts.py      (schedule after the US close, e.g. 3:30 AM IST)
"""
import _bootstrap  # noqa: F401

from sqlalchemy import select

from tradingos import watchlist
from tradingos.alerts import send_alert_notification
from tradingos.db.models import Alert
from tradingos.db.session import session_scope
from tradingos.journal.service import trades_dataframe
from tradingos.services import latest_prices
from tradingos.settings import load_settings


def main() -> None:
    msgs = watchlist.check_alerts()
    ot = trades_dataframe("OPEN")
    if len(ot):
        prices, meta = latest_prices(list(ot["ticker"].unique()))
        with session_scope() as s:
            for _, t in ot.iterrows():
                px = prices.get(t["ticker"])
                if px is None:
                    continue
                if px <= t["current_stop"]:
                    m = f"{t['ticker']} closed {px:.2f} at/below stop {t['current_stop']:.2f} (as of {meta.get('data_as_of')}) — execute your plan"
                elif t["target"] and px >= t["target"]:
                    m = f"{t['ticker']} closed {px:.2f} at/above target {t['target']:.2f} (as of {meta.get('data_as_of')}) — book profit per plan"
                else:
                    continue
                dup = s.scalars(select(Alert).where(Alert.ticker == t["ticker"], Alert.message == m, Alert.acknowledged.is_(False))).first()
                if not dup:
                    s.add(Alert(ticker=t["ticker"], message=m))
                    msgs.append(m)

    if msgs:
        cfg = load_settings()
        send_alert_notification(
            title=f"AI Trading OS: {len(msgs)} Price Alert(s)",
            message="\n".join(msgs),
            cfg=cfg,
        )
        print("\n".join(msgs))
    else:
        print("No alerts.")


if __name__ == "__main__":
    main()
