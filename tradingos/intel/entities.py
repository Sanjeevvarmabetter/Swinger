"""Deterministic entity extraction: countries/regions, institutions and tickers from headline + summary text.

Gazetteer-based (word-boundary matching), so results are explainable and never hallucinated. It will miss
entities that are not listed — extend the dictionaries below as needed.
"""
from __future__ import annotations

from tradingos.data.news import kw_hit

COUNTRIES: dict[str, list[str]] = {
    "United States": ["united states", "u.s.", "america", "american", "washington", "white house", "pentagon"],
    "China": ["china", "chinese", "beijing", "xi jinping"],
    "Taiwan": ["taiwan", "taiwanese", "taipei"],
    "Russia": ["russia", "russian", "moscow", "kremlin", "putin"],
    "Ukraine": ["ukraine", "ukrainian", "kyiv", "zelensky", "zelenskiy"],
    "Israel": ["israel", "israeli", "netanyahu", "idf"],
    "Palestine / Gaza": ["gaza", "palestinian", "west bank", "hamas"],
    "Iran": ["iran", "iranian", "tehran"],
    "Lebanon": ["lebanon", "hezbollah"],
    "Yemen": ["yemen", "houthi", "houthis"],
    "Syria": ["syria", "syrian", "damascus"],
    "Saudi Arabia": ["saudi", "riyadh"],
    "UAE": ["uae", "emirates", "abu dhabi", "dubai"],
    "Qatar": ["qatar", "doha"],
    "Turkey": ["turkey", "turkish", "ankara", "erdogan"],
    "India": ["india", "indian", "new delhi", "modi"],
    "Pakistan": ["pakistan", "pakistani", "islamabad"],
    "Japan": ["japan", "japanese", "tokyo"],
    "South Korea": ["south korea", "korean", "seoul"],
    "North Korea": ["north korea", "pyongyang", "kim jong"],
    "European Union": ["european union", "eu ", "brussels", "european commission"],
    "Germany": ["germany", "german", "berlin"],
    "France": ["france", "french", "paris", "macron"],
    "United Kingdom": ["britain", "british", "uk ", "london", "downing street"],
    "Canada": ["canada", "canadian", "ottawa"],
    "Mexico": ["mexico", "mexican"],
    "Brazil": ["brazil", "brazilian"],
    "Venezuela": ["venezuela", "venezuelan", "maduro"],
    "Argentina": ["argentina", "argentine", "milei"],
    "Australia": ["australia", "australian", "canberra"],
    "Indonesia": ["indonesia", "indonesian", "jakarta"],
    "Vietnam": ["vietnam", "vietnamese", "hanoi"],
    "Philippines": ["philippines", "philippine", "manila"],
    "Egypt": ["egypt", "egyptian", "cairo", "suez"],
    "South Africa": ["south africa"],
    "Nigeria": ["nigeria", "nigerian"],
    "Afghanistan": ["afghanistan", "taliban"],
    "Bangladesh": ["bangladesh", "dhaka"],
    "Sri Lanka": ["sri lanka"],
}
INSTITUTIONS: dict[str, list[str]] = {
    "Federal Reserve": ["federal reserve", "fomc", "powell", "fed chair", "fed "],
    "ECB": ["ecb", "european central bank", "lagarde"],
    "Bank of England": ["bank of england", "boe "],
    "Bank of Japan": ["bank of japan", "boj", "ueda"],
    "RBI": ["rbi", "reserve bank of india", "malhotra"],
    "PBoC": ["pboc", "people's bank of china"],
    "SEBI": ["sebi"],
    "SEC": ["sec ", "securities and exchange commission"],
    "OPEC+": ["opec"],
    "NATO": ["nato"],
    "United Nations": ["united nations", "un security council", "u.n."],
    "IMF": ["imf", "international monetary fund"],
    "World Bank": ["world bank"],
    "WTO": ["wto", "world trade organization"],
    "US Treasury": ["treasury secretary", "us treasury", "u.s. treasury", "ofac"],
    "US Commerce Dept": ["commerce department", "bureau of industry and security", "entity list"],
    "White House": ["white house", "trump administration", "president trump"],
}


def extract(text: str) -> dict[str, list[str]]:
    t = f" {text} "
    return {
        "countries": [c for c, kws in COUNTRIES.items() if any(kw_hit(t, k) for k in kws)],
        "institutions": [i for i, kws in INSTITUTIONS.items() if any(kw_hit(t, k) for k in kws)],
    }
