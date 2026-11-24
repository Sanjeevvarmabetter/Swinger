"""Push notification dispatcher for price and risk alerts.

Supports:
  1. ntfy.sh (free, instant push notifications to mobile/browser with no account needed)
  2. Telegram Bot (via Bot API)
  3. Generic Webhook (Discord / Slack / custom HTTP endpoint)
"""
from __future__ import annotations

import logging
from typing import Any

import requests

from tradingos.settings import TradingSettings, load_settings

log = logging.getLogger(__name__)


def send_alert_notification(
    title: str,
    message: str,
    cfg: TradingSettings | None = None,
) -> dict[str, bool]:
    """Dispatch an alert message across all configured notification channels."""
    cfg = cfg or load_settings()
    results: dict[str, bool] = {}

    # 1. ntfy.sh
    if cfg.alert_ntfy_topic:
        topic = cfg.alert_ntfy_topic.strip()
        url = topic if topic.startswith("http") else f"https://ntfy.sh/{topic}"
        try:
            r = requests.post(
                url,
                data=message.encode("utf-8"),
                headers={"Title": title, "Tags": "bell,chart_with_upwards_trend", "Priority": "4"},
                timeout=10,
            )
            results["ntfy"] = r.status_code == 200
        except Exception as e:
            log.warning("ntfy alert failed: %s", e)
            results["ntfy"] = False

    # 2. Telegram Bot
    if cfg.alert_telegram_bot_token and cfg.alert_telegram_chat_id:
        token = cfg.alert_telegram_bot_token.strip()
        chat_id = cfg.alert_telegram_chat_id.strip()
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": f"🚨 *{title}*\n\n{message}",
            "parse_mode": "Markdown",
        }
        try:
            r = requests.post(url, json=payload, timeout=10)
            results["telegram"] = r.status_code == 200
        except Exception as e:
            log.warning("Telegram alert failed: %s", e)
            results["telegram"] = False

    # 3. Webhook (Discord / Slack / Generic)
    if cfg.alert_webhook_url:
        webhook_url = cfg.alert_webhook_url.strip()
        payload = {
            "title": title,
            "text": message,
            "content": f"🚨 **{title}**\n{message}",
        }
        try:
            r = requests.post(webhook_url, json=payload, timeout=10)
            results["webhook"] = r.status_code in (200, 204)
        except Exception as e:
            log.warning("Webhook alert failed: %s", e)
            results["webhook"] = False

    return results


def test_notification(cfg: TradingSettings | None = None) -> dict[str, str]:
    """Send a test ping and return status message for each configured channel."""
    cfg = cfg or load_settings()
    out: dict[str, str] = {}
    if not (cfg.alert_ntfy_topic or (cfg.alert_telegram_bot_token and cfg.alert_telegram_chat_id) or cfg.alert_webhook_url):
        return {"none": "No notification channels configured. Configure ntfy, Telegram, or Webhook below."}

    res = send_alert_notification("AI Trading OS Test Alert", "Test notification from your research terminal! 📈", cfg)
    for channel, ok in res.items():
        out[channel] = "✅ Delivered successfully" if ok else "❌ Failed to send (check configuration)"
    return out
