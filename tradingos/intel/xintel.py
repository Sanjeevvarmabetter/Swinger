"""X (Twitter) Intelligence via the official X API v2 recent-search endpoint.

* Requires X_BEARER_TOKEN (app-only auth). Without it the page states that X is not configured — nothing is invented.
* X API access is pay-per-use, so every list is cached (default 30 min) and a daily request budget is enforced
  (X_DAILY_REQUEST_LIMIT, default 40). Posts are shown as reported by the account; they are not verified facts.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

from tradingos.config import PROJECT_ROOT, _env
from tradingos.data import cache

API = "https://api.x.com/2/tweets/search/recent"
CONFIG = PROJECT_ROOT / "config" / "x_sources.json"
_BUDGET_KEY = "x|budget"


@dataclass
class XResult:
    key: str
    title: str
    posts: list[dict] = field(default_factory=list)
    error: str | None = None
    fetched_at_utc: str = ""
    from_cache: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None


def bearer() -> str:
    return _env("X_BEARER_TOKEN")


def configured() -> bool:
    return bool(bearer())


def daily_limit() -> int:
    try:
        return max(0, int(_env("X_DAILY_REQUEST_LIMIT", "40")))
    except ValueError:
        return 40


def cache_minutes() -> int:
    try:
        return max(5, int(_env("X_CACHE_MINUTES", "30")))
    except ValueError:
        return 30


def load_lists(path: Path = CONFIG) -> list[dict]:
    try:
        return json.loads(path.read_text())["lists"]
    except Exception:
        return []


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def budget_used() -> int:
    b = cache.get(_BUDGET_KEY, 48 * 3600) or {}
    return int(b.get(_today(), 0))


def _spend() -> None:
    b = cache.get(_BUDGET_KEY, 48 * 3600) or {}
    b = {_today(): int(b.get(_today(), 0)) + 1}
    cache.put(_BUDGET_KEY, b)


def parse_response(data: dict) -> list[dict]:
    users = {u["id"]: u for u in (data.get("includes", {}) or {}).get("users", [])}
    out = []
    for t in data.get("data", []) or []:
        u = users.get(t.get("author_id"), {})
        handle = u.get("username", "")
        m = t.get("public_metrics", {}) or {}
        out.append({
            "id": t["id"], "text": t.get("text", ""), "created_utc": (t.get("created_at") or "")[:16].replace("T", " "),
            "author": u.get("name", handle), "handle": handle, "verified": bool(u.get("verified")),
            "likes": m.get("like_count", 0), "reposts": m.get("retweet_count", 0), "replies": m.get("reply_count", 0),
            "url": f"https://x.com/{handle or 'i'}/status/{t['id']}",
        })
    return out


def fetch_list(item: dict, force: bool = False, max_results: int = 20) -> XResult:
    key, title = item["key"], item.get("title", item["key"])
    if not configured():
        return XResult(key, title, error="X API not configured (X_BEARER_TOKEN missing).")
    ck = f"x|list|{key}|{item['query']}"
    if not force:
        hit = cache.get(ck, cache_minutes() * 60)
        if hit is not None:
            return XResult(key, title, hit["posts"], None, hit["fetched_at_utc"], from_cache=True)
    if budget_used() >= daily_limit():
        stale = cache.get(ck, 7 * 24 * 3600)
        msg = f"Daily X request budget reached ({daily_limit()} requests; raise X_DAILY_REQUEST_LIMIT to change)."
        if stale is not None:
            return XResult(key, title, stale["posts"], msg + " Showing the last cached result.",
                           stale["fetched_at_utc"], from_cache=True)
        return XResult(key, title, error=msg)
    params = {"query": item["query"], "max_results": max(10, min(100, max_results)),
              "tweet.fields": "created_at,public_metrics,author_id,lang", "expansions": "author_id",
              "user.fields": "username,name,verified"}
    try:
        _spend()
        r = requests.get(API, params=params, headers={"Authorization": f"Bearer {bearer()}"}, timeout=20)
    except requests.RequestException as e:
        return XResult(key, title, error=f"Network error contacting X API ({type(e).__name__}).")
    if r.status_code == 401:
        return XResult(key, title, error="X API rejected the bearer token (401). Check X_BEARER_TOKEN.")
    if r.status_code == 402 or r.status_code == 403:
        return XResult(key, title, error=f"X API refused the request (HTTP {r.status_code}) — the account's plan or "
                                         "credit balance does not allow recent search.")
    if r.status_code == 429:
        reset = r.headers.get("x-rate-limit-reset")
        when = (f" Resets at {datetime.fromtimestamp(int(reset), timezone.utc):%H:%M} UTC." if reset and reset.isdigit()
                else "")
        return XResult(key, title, error="X API rate limit reached (429)." + when)
    if r.status_code != 200:
        return XResult(key, title, error=f"X API error HTTP {r.status_code}.")
    try:
        posts = parse_response(r.json())
    except ValueError:
        return XResult(key, title, error="X API returned an unreadable response.")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cache.put(ck, {"posts": posts, "fetched_at_utc": stamp, "ts": time.time()})
    return XResult(key, title, posts, None, stamp)


def briefing_section(max_per_list: int = 3) -> dict:
    """Cached-only X summary for the briefing payload (never spends API budget)."""
    if not configured():
        return {"status": "X integration not configured (X_BEARER_TOKEN missing) — no X data in this briefing."}
    out = []
    for item in load_lists():
        hit = cache.get(f"x|list|{item['key']}|{item['query']}", 12 * 3600)
        if hit:
            top = sorted(hit["posts"], key=lambda p: p["likes"] + 2 * p["reposts"], reverse=True)[:max_per_list]
            out.append({"list": item.get("title"), "fetched_at_utc": hit["fetched_at_utc"],
                        "posts": [{k: p[k] for k in ("author", "handle", "created_utc", "text", "url")} for p in top]})
    if not out:
        return {"status": "X configured but no posts cached in the last 12h — open X Intelligence to fetch."}
    return {"status": "Posts are what accounts said, not verified facts.", "lists": out}
