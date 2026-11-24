"""Global market intelligence layer (briefings, cross-market snapshots, gold, calendars, health).

Same rules as the rest of the app: Python fetches and computes every number, each item carries its
source / timestamps / freshness, and Gemini only interprets the structured payloads built here.
"""
