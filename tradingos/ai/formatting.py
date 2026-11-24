"""Post-processing of AI answers before they are rendered as Markdown.

Everything here is deterministic and conservative: it fixes presentation problems (reasoning tags, whole-answer code
fences, malformed tables, raw JSON, repeated paragraphs) and enforces one content rule — links may only point to URLs
that were actually supplied to the model. It never adds facts.
"""
from __future__ import annotations

import json
import re
from typing import Iterable

_THINK = re.compile(r"<think>.*?(</think>|$)", re.S | re.I)
_FENCE_WRAP = re.compile(r"^\s*```(?:markdown|md|text)?\s*\n(.*?)\n```\s*$", re.S | re.I)
_MD_LINK = re.compile(r"(?<!!)\[([^\]\n]{1,300})\]\((https?://[^\s)]+)\)")
_BARE_URL = re.compile(r"(?<![(\[<\"'=])\bhttps?://[^\s)\]>]+")
_SIGNED_PCT = re.compile(r"(?<![\w/=.\-+:\[])([+\-−]\d{1,4}(?:[.,]\d+)?\s?%)(?![\w\]])")
_SEP_CELL = re.compile(r"^\s*:?-+:?\s*$")


_ID = r"[NCGB]\d{1,3}"
# [N3] · 【N3】 · (N3) · [N1, N4] · (Economic Times, N4) — an optional short source label may precede the ids.
_CITE_IDS = re.compile(r"[\[【(]\s*(?:[^\[\]【】()\n]{1,40}?[,:]\s*)?((?:" + _ID + r")(?:\s*[,;†]\s*(?:" + _ID +
                       r"))*)\s*[\]】)]")
_BARE_NEWS_ID = re.compile(r"(?<![\w\[(/-])([NC]\d{1,2})(?![\w\])-])")
_FULLWIDTH_REF = re.compile(r"【[^】\n]{0,80}】")
_UNICODE_FIX = {"\u2011": "-", "\u2010": "-", "\u2212": "-", "\u202f": " ", "\u00a0": " ", "\u2009": " "}


# ----------------------------------------------------------------------------- small helpers
def normalize_unicode(text: str) -> str:
    """Replace non-breaking hyphens, minus signs and narrow/no-break spaces some models emit with plain ASCII."""
    # thousands separators written as (narrow) no-break spaces: 7 196.87 → 7,196.87
    text = re.sub(r"(?<=\d)[\u202f\u2009\u00a0](?=\d{3}(?!\d))", ",", text)
    # an en/em dash used as a minus sign on a number: –0.56% → -0.56%
    text = re.sub(r"(?<![\w.])[\u2013\u2014](?=\d[\d.,]*\s?%)", "-", text)
    for a, b in _UNICODE_FIX.items():
        text = text.replace(a, b)
    text = re.sub(r"(\d) %", r"\1%", text)
    return re.sub(r"(?<=\S) {2,}(?=\S)", " ", text)


def link_citations(text: str, sources: list[dict]) -> tuple[str, set[str]]:
    """Turn id markers ([N3], 【N3】, [N1, N4]) into links to the source URL. Unknown ids and other 【…】 markers
    (e.g. 【data】) are removed — a citation is either verified or not shown. Returns (text, cited_urls)."""
    by_id = {i: s for s in sources for i in [s.get("id"), *s.get("aliases", [])] if i}
    cited: set[str] = set()
    out = []
    for is_code, chunk in _split_code(text):
        if is_code:
            out.append(chunk)
            continue

        def repl(m):
            links = []
            for i in re.split(r"\s*[,;†]\s*", m.group(1)):
                s = by_id.get(i)
                if s:
                    cited.add(s["url"])
                    label = str(s.get("source") or "source").split(" (via")[0].replace("[", "(").replace("]", ")")
                    links.append(f"[{label}]({s['url']})")
            return (" " + " · ".join(links)) if links else ""

        chunk = _CITE_IDS.sub(repl, chunk)

        def bare(m):   # only ids that exist; "G7", "B2B" etc. are never touched (G/B excluded, unknown ids kept)
            s = by_id.get(m.group(2))
            if not s:
                return m.group(0)
            cited.add(s["url"])
            label = str(s.get("source") or "source").split(" (via")[0].replace("[", "(").replace("]", ")")
            return f"[{label}]({s['url']})"

        chunk = re.sub(r"(\]\([^)]*\))|" + _BARE_NEWS_ID.pattern, lambda m: m.group(1) or bare(m), chunk)
        chunk = _FULLWIDTH_REF.sub("", chunk)
        chunk = re.sub(r"[ \t]+([.,;:])", r"\1", chunk)
        chunk = re.sub(r"(?<=\S) {2,}(?=\S)", " ", chunk)
        out.append(chunk)
    return "".join(out), cited

def strip_reasoning(text: str) -> str:
    """Remove <think>…</think> blocks some open models emit (also an unterminated one while streaming)."""
    return _THINK.sub("", text or "")


def unwrap_fence(text: str) -> str:
    """If the whole answer is wrapped in ```markdown … ``` the renderer would show raw syntax — unwrap it."""
    m = _FENCE_WRAP.match(text or "")
    return m.group(1) if m else (text or "")


def _split_code(text: str) -> list[tuple[bool, str]]:
    """Split into (is_code, chunk) so transformations never touch fenced code blocks."""
    parts, out = re.split(r"(```.*?```)", text, flags=re.S), []
    for p in parts:
        if p:
            out.append((p.startswith("```") and p.endswith("```") and len(p) >= 6, p))
    return out


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_table_line(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


def normalize_tables(text: str) -> str:
    """Repair Markdown tables: blank line before/after, a separator row after the header, equal cell counts.

    A "table" is a run of ≥2 consecutive lines that start with '|'. Single stray '|' lines are left alone.
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        if not _is_table_line(lines[i]):
            out.append(lines[i])
            i += 1
            continue
        j = i
        while j < len(lines) and _is_table_line(lines[j]):
            j += 1
        block = lines[i:j]
        if len(block) < 2:
            out.extend(block)
            i = j
            continue
        header = _cells(block[0])
        ncol = len(header)
        rows = block[1:]
        if rows and all(_SEP_CELL.match(c) for c in _cells(rows[0]) if c != "") and _cells(rows[0]):
            rows = rows[1:]
        fixed = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * ncol) + "|"]
        for r in rows:
            c = _cells(r)
            if all(_SEP_CELL.match(x) for x in c if x != ""):     # stray separator rows
                continue
            c = (c + [""] * ncol)[:ncol] if len(c) <= ncol else c[: ncol - 1] + [" ".join(c[ncol - 1:])]
            fixed.append("| " + " | ".join(c) + " |")
        if out and out[-1].strip():
            out.append("")
        out.extend(fixed)
        if j < len(lines) and lines[j].strip():
            out.append("")
        i = j
    return "\n".join(out)


def json_to_markdown(text: str) -> str:
    """If the model answered with raw JSON, render it as readable Markdown bullets instead."""
    s = (text or "").strip()
    fence = re.match(r"^```(?:json)?\s*\n(.*)\n```$", s, re.S)
    if fence:
        s = fence.group(1).strip()
    if not s or s[0] not in "{[":
        return text
    try:
        obj = json.loads(s)
    except ValueError:
        return text

    def render(o, depth=0) -> list[str]:
        pad = "  " * depth
        if isinstance(o, dict):
            lines = []
            for k, v in o.items():
                label = str(k).replace("_", " ").strip().capitalize()
                if isinstance(v, (dict, list)):
                    lines.append(f"{pad}- **{label}:**")
                    lines += render(v, depth + 1)
                else:
                    lines.append(f"{pad}- **{label}:** {v}")
            return lines
        if isinstance(o, list):
            lines = []
            for v in o:
                if isinstance(v, (dict, list)):
                    sub = render(v, depth + 1)
                    lines.append(f"{pad}- " + sub[0].strip().lstrip("- ") if sub else f"{pad}-")
                    lines += sub[1:]
                else:
                    lines.append(f"{pad}- {v}")
            return lines
        return [f"{pad}{o}"]

    return "\n".join(render(obj))


def dedupe_paragraphs(text: str) -> str:
    """Drop exact repeated paragraphs (some models loop) while keeping order and code blocks intact."""
    seen, out = set(), []
    for para in re.split(r"\n{2,}", text):
        key = re.sub(r"\s+", " ", para).strip().lower()
        if len(key) > 60 and key in seen and "```" not in para:
            continue
        seen.add(key)
        out.append(para)
    return "\n\n".join(out)


def _norm_url(u: str) -> str:
    return u.strip().rstrip(".,;:").rstrip("/").lower()


def enforce_citations(text: str, allowed_urls: Iterable[str]) -> tuple[str, int]:
    """Keep links only if their URL was supplied in the context. Others are unlinked and flagged.

    Returns (text, number_of_links_removed).
    """
    allowed = {_norm_url(u) for u in allowed_urls if u}
    removed = 0
    out = []
    for is_code, chunk in _split_code(text):
        if is_code:
            out.append(chunk)
            continue

        def link(m):
            nonlocal removed
            label, url = m.group(1), m.group(2)
            if _norm_url(url) in allowed:
                return m.group(0)
            removed += 1
            return f"{label} _(unverified link removed)_"

        chunk = _MD_LINK.sub(link, chunk)

        def bare(m):
            nonlocal removed
            if _norm_url(m.group(0)) in allowed:
                return f"<{m.group(0)}>"
            removed += 1
            return "_(unverified link removed)_"

        # bare URLs: only those not already inside a markdown link target (those were handled above)
        chunk = re.sub(r"(\]\([^)]*\))|" + _BARE_URL.pattern,
                       lambda m: m.group(1) if m.group(1) else bare(m), chunk)
        out.append(chunk)
    return "".join(out), removed


def color_moves(text: str) -> str:
    """Colour signed percentage moves green/red using Streamlit Markdown colour directives.

    Skips code blocks, link targets and existing colour directives.
    """
    out = []
    for is_code, chunk in _split_code(text):
        if is_code:
            out.append(chunk)
            continue
        pieces = re.split(r"(\]\([^)]*\)|:(?:green|red|orange|blue|gray|violet|rainbow)\[[^\]]*\]|`[^`\n]*`)", chunk)
        for k, p in enumerate(pieces):
            if k % 2 == 1:
                out.append(p)
                continue

            def paint(m):
                v = m.group(1)
                colour = "green" if v.startswith("+") else "red"
                return f":{colour}[{v.replace('−', '-')}]"

            out.append(_SIGNED_PCT.sub(paint, p))
    return "".join(out)


def close_partial(text: str, sources: list[dict] | None = None) -> str:
    """Make a partially streamed answer render cleanly: close an open code fence, drop a half-written table row,
    and (if sources are given) show citation markers as links already while streaming."""
    t = normalize_unicode(strip_reasoning(text))
    if sources:
        t, _ = link_citations(t, sources)
    if t.count("```") % 2 == 1:
        t += "\n```"
    lines = t.split("\n")
    if len(lines) > 1 and _is_table_line(lines[-1]) and not lines[-1].rstrip().endswith("|"):
        lines = lines[:-1]
    return "\n".join(lines)


# ----------------------------------------------------------------------------- main entry point
def clean_answer(text: str, allowed_urls: Iterable[str] | None = None, colour: bool = True,
                 sources: list[dict] | None = None) -> tuple[str, dict]:
    """Full post-processing pipeline. Returns (markdown, report) where report lists what was changed.

    `sources` (with ids) enables id-citation linking; `report["cited_urls"]` then lists the sources actually cited.
    """
    report: dict = {}
    t = normalize_unicode(strip_reasoning(text or "")).strip()
    t2 = unwrap_fence(t)
    if t2 != t:
        report["unwrapped_fence"] = True
    t3 = json_to_markdown(t2)
    if t3 != t2:
        report["json_rendered"] = True
    t4 = normalize_tables(t3)
    if t4 != t3:
        report["tables_repaired"] = True
    t5 = dedupe_paragraphs(t4)
    if t5 != t4:
        report["duplicates_removed"] = True
    if sources is not None:
        t5, cited = link_citations(t5, sources)
        report["cited_urls"] = sorted(cited)
    if allowed_urls is not None:
        t5, n = enforce_citations(t5, allowed_urls)
        if n:
            report["links_removed"] = n
    if colour:
        t5 = color_moves(t5)
    return t5.strip(), report


def sources_markdown(sources: list[dict], cited_only_urls: Iterable[str] | None = None) -> str:
    """Numbered, clickable source list built from the context (never from model output)."""
    if not sources:
        return ""
    cited = {_norm_url(u) for u in cited_only_urls} if cited_only_urls is not None else None
    rows = []
    for s in sources:
        if cited is not None and _norm_url(s.get("url", "")) not in cited:
            continue
        when = f" · {s['published']}" if s.get("published") else ""
        title = str(s.get("title", "")).replace("[", "(").replace("]", ")")
        rows.append(f"{len(rows) + 1}. [{title}]({s['url']}) — {s.get('source', '')}{when}")
    return "\n".join(rows)


def cited_urls(text: str) -> list[str]:
    return [m.group(2) for m in _MD_LINK.finditer(text or "")]
