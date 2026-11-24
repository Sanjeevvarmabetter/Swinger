"""Screenshot and chart snapshot storage for the trading journal.

Stores trade setup and exit charts in data/screenshots/ so reflections have visual context.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from tradingos.config import load_config


def get_screenshots_dir() -> Path:
    cfg = load_config()
    d = cfg.data_dir / "screenshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_screenshot(trade_id: int, file_bytes: bytes, original_filename: str) -> str:
    """Save an uploaded image file into data/screenshots/ and return its path."""
    d = get_screenshots_dir()
    clean_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", original_filename)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_name = f"trade_{trade_id}_{timestamp}_{clean_name}"
    dest_path = d / dest_name
    dest_path.write_bytes(file_bytes)
    return str(dest_path)


def list_screenshots(trade_id: int) -> list[Path]:
    """Find all saved screenshots for a given trade."""
    d = get_screenshots_dir()
    return sorted(d.glob(f"trade_{trade_id}_*"))
