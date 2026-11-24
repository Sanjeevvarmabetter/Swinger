"""Registry of tracked cross-market instruments and the exchanges they trade on.

Symbols were verified against Yahoo Finance on 2026-11-24. Index symbols whose Yahoo history was
empty or single-bar at that time (e.g. Nifty Smallcap 100, Nifty Defence, Nifty Media, MCX gold)
are deliberately NOT listed — they are reported as unavailable instead of shown with bad data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Market:
    key: str
    label: str
    tz: ZoneInfo
    close: time            # local regular-session close
    weekdays_only: bool = True
    calendar_note: str = "Weekday calendar — exchange holidays are not modelled."


MARKETS: dict[str, Market] = {
    "US": Market("US", "NYSE/Nasdaq", ZoneInfo("America/New_York"), time(16, 0),
                 calendar_note="NYSE holiday calendar applied."),
    "IN": Market("IN", "NSE/BSE", ZoneInfo("Asia/Kolkata"), time(15, 30)),
    "UK": Market("UK", "LSE", ZoneInfo("Europe/London"), time(16, 30)),
    "DE": Market("DE", "Xetra", ZoneInfo("Europe/Berlin"), time(17, 30)),
    "EU": Market("EU", "Eurex/Euronext", ZoneInfo("Europe/Berlin"), time(17, 30)),
    "JP": Market("JP", "TSE", ZoneInfo("Asia/Tokyo"), time(15, 30)),
    "HK": Market("HK", "HKEX", ZoneInfo("Asia/Hong_Kong"), time(16, 0)),
    "CN": Market("CN", "SSE", ZoneInfo("Asia/Shanghai"), time(15, 0)),
    "KR": Market("KR", "KRX", ZoneInfo("Asia/Seoul"), time(15, 30)),
    "AU": Market("AU", "ASX", ZoneInfo("Australia/Sydney"), time(16, 0)),
    # Near-24h markets: a daily bar is "complete" at the NY 17:00 roll.
    "FX": Market("FX", "FX (OTC)", ZoneInfo("America/New_York"), time(17, 0),
                 calendar_note="24×5 market; daily bar rolls at 17:00 New York."),
    "FUT": Market("FUT", "CME/NYMEX/COMEX futures", ZoneInfo("America/New_York"), time(17, 0),
                  calendar_note="Nearly 24×5 futures; continuous front-month contract; CME holidays not modelled."),
    "CRYPTO": Market("CRYPTO", "Crypto (24×7)", ZoneInfo("UTC"), time(0, 0), weekdays_only=False,
                     calendar_note="Trades 24×7; daily bar is the UTC day."),
}


@dataclass(frozen=True)
class Instrument:
    name: str
    symbol: str
    group: str
    market: str
    unit: str = ""
    note: str = ""


def _g(group: str, market: str, items: list[tuple], unit: str = "") -> list[Instrument]:
    out = []
    for it in items:
        name, sym = it[0], it[1]
        note = it[2] if len(it) > 2 else ""
        out.append(Instrument(name, sym, group, market, unit, note))
    return out


INSTRUMENTS: list[Instrument] = [
    *_g("US indices", "US", [("S&P 500", "^GSPC"), ("Nasdaq 100", "^NDX"), ("Dow Jones", "^DJI"),
                             ("Russell 2000", "^RUT"), ("S&P 500 equal-weight (RSP)", "RSP")]),
    *_g("Volatility", "US", [("VIX", "^VIX"), ("MOVE (bond vol)", "^MOVE")]),
    *_g("US Treasury yields", "US", [("US 3M yield", "^IRX"), ("US 5Y yield", "^FVX"), ("US 10Y yield", "^TNX"),
                                     ("US 30Y yield", "^TYX")], unit="%"),
    *_g("Credit & bonds", "US", [("20Y+ Treasuries (TLT)", "TLT"), ("High yield (HYG)", "HYG"),
                                 ("IG corporate (LQD)", "LQD")]),
    *_g("Currencies", "FX", [("US Dollar Index (DXY)", "DX-Y.NYB"), ("EUR/USD", "EURUSD=X"), ("USD/JPY", "JPY=X"),
                             ("USD/INR", "INR=X")]),
    *_g("Europe", "UK", [("FTSE 100", "^FTSE")]),
    *_g("Europe", "DE", [("DAX", "^GDAXI")]),
    *_g("Europe", "EU", [("Euro Stoxx 50", "^STOXX50E")]),
    *_g("Asia-Pacific", "JP", [("Nikkei 225", "^N225")]),
    *_g("Asia-Pacific", "HK", [("Hang Seng", "^HSI")]),
    *_g("Asia-Pacific", "CN", [("Shanghai Composite", "000001.SS")]),
    *_g("Asia-Pacific", "KR", [("KOSPI", "^KS11")]),
    *_g("Asia-Pacific", "AU", [("ASX 200", "^AXJO")]),
    *_g("India", "IN", [("Nifty 50", "^NSEI"), ("Sensex", "^BSESN"), ("Bank Nifty", "^NSEBANK"),
                        ("Nifty Next 50", "^NSMIDCP"), ("Nifty 100", "^CNX100"), ("Nifty 500", "^CRSLDX"),
                        ("Nifty Midcap 50", "^NSEMDCP50"), ("Nifty Smallcap 250", "NIFTYSMLCAP250.NS"),
                        ("India VIX", "^INDIAVIX")]),
    *_g("India sectors", "IN", [("Nifty Bank", "^NSEBANK"), ("Nifty Financial Services", "NIFTY_FIN_SERVICE.NS"),
                                ("Nifty IT", "^CNXIT"), ("Nifty Auto", "^CNXAUTO"), ("Nifty Pharma", "^CNXPHARMA"),
                                ("Nifty FMCG", "^CNXFMCG"), ("Nifty Metal", "^CNXMETAL"),
                                ("Nifty Realty", "^CNXREALTY"), ("Nifty Energy", "^CNXENERGY"),
                                ("Nifty PSU Bank", "^CNXPSUBANK"), ("Nifty Infrastructure", "^CNXINFRA"),
                                ("Nifty PSE", "^CNXPSE"), ("Nifty Consumption", "^CNXCONSUM"),
                                ("Nifty MNC", "^CNXMNC")]),
    *_g("Precious metals", "FUT", [("Gold (COMEX front-month)", "GC=F"), ("Silver (COMEX)", "SI=F"),
                                   ("Platinum (NYMEX)", "PL=F")], unit="USD/oz"),
    *_g("Gold proxies", "US", [("SPDR Gold Shares (GLD)", "GLD"), ("Gold miners (GDX)", "GDX")]),
    *_g("Gold proxies", "IN", [("Nippon India Gold BeES (NSE)", "GOLDBEES.NS",
                                "Indian gold ETF — a listed proxy, not the MCX gold contract.")]),
    *_g("Energy & industrial", "FUT", [("WTI crude", "CL=F"), ("Brent crude", "BZ=F"), ("Natural gas (Henry Hub)", "NG=F"),
                                       ("Copper (COMEX)", "HG=F"), ("Wheat (CBOT)", "ZW=F")]),
    *_g("Crypto", "CRYPTO", [("Bitcoin", "BTC-USD")]),
]

US_SECTORS = {
    "Technology": "XLK", "Communication Services": "XLC", "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP", "Energy": "XLE", "Financials": "XLF", "Health Care": "XLV",
    "Industrials": "XLI", "Materials": "XLB", "Real Estate": "XLRE", "Utilities": "XLU",
}
US_THEMES = {
    "Semiconductors (SMH)": "SMH", "Software (IGV)": "IGV", "Cloud (SKYY)": "SKYY",
    "Cybersecurity (CIBR)": "CIBR", "AI & big data (AIQ)": "AIQ", "Robotics & AI (BOTZ)": "BOTZ",
    "Aerospace & defence (ITA)": "ITA", "Uranium & nuclear (URA)": "URA", "Clean energy (ICLN)": "ICLN",
    "Gold miners (GDX)": "GDX", "China internet (KWEB)": "KWEB", "Emerging markets (EEM)": "EEM",
    "India (INDA)": "INDA",
}
MAG7 = {"Apple": "AAPL", "Microsoft": "MSFT", "Nvidia": "NVDA", "Alphabet": "GOOGL", "Amazon": "AMZN",
        "Meta": "META", "Tesla": "TSLA"}

GEO_SENSITIVE = {"TSMC (ADR)": "TSM", "ASML": "ASML", "Applied Materials": "AMAT", "MP Materials": "MP",
                 "Rare earths & strategic metals (REMX)": "REMX"}

for _grp, _m in (("US sectors", US_SECTORS), ("US themes", US_THEMES), ("Magnificent 7", MAG7),
                 ("Geo-sensitive stocks", GEO_SENSITIVE)):
    INSTRUMENTS += _g(_grp, "US", list(_m.items()))

UNAVAILABLE = [
    ("MCX gold / silver futures", "No authorised free API in this app. Shown instead: COMEX gold converted to "
     "INR per 10 g (excludes import duty, GST and local premium) and the GOLDBEES ETF.",
     "https://www.mcxindia.com/market-data/market-watch"),
    ("FII / DII daily flows", "NSE publishes these on its website only; this app does not scrape NSE.",
     "https://www.nseindia.com/reports/fii-dii"),
    ("NSE / BSE corporate announcements, bulk & block deals", "No authorised API configured.",
     "https://www.nseindia.com/companies-listing/corporate-filings-announcements"),
    ("Nifty Smallcap 100, Nifty Defence, Nifty Media, Nifty Healthcare", "Yahoo history empty or single-bar when verified.",
     "https://www.niftyindices.com/"),
    ("Fed funds futures / rate-cut probabilities", "CME FedWatch has no free API; not estimated here.",
     "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"),
    ("Gold ETF flows & central-bank purchases", "World Gold Council data has no free API.",
     "https://www.gold.org/goldhub/data"),
    ("India / China physical gold demand", "Published quarterly by the World Gold Council (no API).",
     "https://www.gold.org/goldhub/research/gold-demand-trends"),
]


def by_group(group: str) -> list[Instrument]:
    return [i for i in INSTRUMENTS if i.group == group]


def groups() -> list[str]:
    return list(dict.fromkeys(i.group for i in INSTRUMENTS))


def find(symbol: str) -> Instrument | None:
    return next((i for i in INSTRUMENTS if i.symbol == symbol), None)
