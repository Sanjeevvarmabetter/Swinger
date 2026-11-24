"""Tiny disk cache (pickle) with TTL, used to avoid hammering free data sources."""
from __future__ import annotations

import hashlib
import pickle
import time
from pathlib import Path
from typing import Any, Callable

from tradingos.config import load_config


def _path(key: str) -> Path:
    h = hashlib.sha1(key.encode()).hexdigest()[:20]
    return load_config().cache_dir / f"{h}.pkl"


def get(key: str, ttl_seconds: float) -> Any | None:
    p = _path(key)
    if not p.exists() or (time.time() - p.stat().st_mtime) > ttl_seconds:
        return None
    try:
        with p.open("rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def put(key: str, value: Any) -> None:
    p = _path(key)
    tmp = p.with_suffix(".tmp")
    with tmp.open("wb") as f:
        pickle.dump(value, f)
    tmp.replace(p)


def cached(key: str, ttl_seconds: float, fn: Callable[[], Any], force: bool = False) -> Any:
    if not force:
        hit = get(key, ttl_seconds)
        if hit is not None:
            return hit
    val = fn()
    if val is not None:
        put(key, val)
    return val


def clear() -> int:
    n = 0
    for p in load_config().cache_dir.glob("*.pkl"):
        p.unlink(missing_ok=True)
        n += 1
    return n
