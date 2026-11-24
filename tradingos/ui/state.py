"""Cached data accessors for the Streamlit pages (thin wrappers over services)."""
from __future__ import annotations

import json
from dataclasses import asdict

import streamlit as st

from tradingos import services
from tradingos.settings import AppSettings, load_settings


def _cfg_from(cfg_json: str) -> AppSettings:
    return AppSettings.from_dict(json.loads(cfg_json))


@st.cache_data(ttl=900, show_spinner=False)
def _market_ctx(cfg_json: str, include_macro: bool, nonce: int) -> dict:  # noqa: ARG001
    return services.market_context(_cfg_from(cfg_json), include_macro=include_macro)


def market_ctx(include_macro: bool = True) -> dict:
    cfg = load_settings()
    return _market_ctx(json.dumps(asdict(cfg)), include_macro, st.session_state.get("mkt_nonce", 0))


def refresh_market() -> None:
    """Force a re-download on next access."""
    from tradingos.data import cache
    cache.clear()
    st.session_state["mkt_nonce"] = st.session_state.get("mkt_nonce", 0) + 1
    st.cache_data.clear()


@st.cache_data(ttl=900, show_spinner=False)
def _stock_ctx(ticker: str, cfg_json: str, nonce: int) -> dict:  # noqa: ARG001
    return services.stock_context(ticker, _cfg_from(cfg_json))


def stock_ctx(ticker: str) -> dict:
    cfg = load_settings()
    return _stock_ctx(ticker.upper().strip(), json.dumps(asdict(cfg)), st.session_state.get("mkt_nonce", 0))


def selected_ticker(default: str = "") -> str:
    return st.session_state.get("ticker", default)


def select_ticker(t: str) -> None:
    st.session_state["ticker"] = t.upper().strip()


def valid_ticker(t: str) -> bool:
    t = t.strip().upper()
    return 0 < len(t) <= 12 and all(ch.isalnum() or ch in ".-^=" for ch in t)
