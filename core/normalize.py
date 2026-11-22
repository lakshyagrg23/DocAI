"""Value normalisation shared by fact extraction (M5) and the verifier (M4): facts-and-subjects.md §3.

`parse_value` turns raw text into a FactValue. `number_tokens` lists the comparable numeric tokens of a sentence so
a claim's numbers can be checked against the source text with the very same rules.
"""
from __future__ import annotations

import re

from core.models import FactValue

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9

_MON = "|".join(sorted(MONTHS, key=len, reverse=True))
_NUM = r"\d[\d,]*(?:\.\d+)?"
_SCALE = {"lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "crore": 1e7, "crores": 1e7}

RE_DMY = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MON})\.?,?\s+(\d{{4}})\b", re.IGNORECASE)
RE_MDY = re.compile(rf"\b({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.IGNORECASE)
RE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
RE_SLASH = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")
RE_PCT = re.compile(rf"({_NUM})\s*(?:%|per\s*cent\b|percent\b)", re.IGNORECASE)
RE_MONEY = re.compile(rf"(?:₹|rs\.?|inr)\s*({_NUM})(?:\s*(lakhs?|lac|crores?))?|({_NUM})\s*(lakhs?|lac|crores?)|({_NUM})\s*/-", re.IGNORECASE)
RE_PLAIN = re.compile(rf"(?<![\w.])({_NUM})(?:st|nd|rd|th)?(?![\w])", re.IGNORECASE)
RE_CLAUSE_REF = re.compile(
    r"\b(?:clauses?|cl\.?|paras?\.?|paragraphs?|sections?|sec\.?|articles?|art\.?|annexure|table|row|page|p\.)\s*"
    r"[A-Za-z]?\d+(?:\.\d+)*(?:\s*\(\w\))?", re.IGNORECASE)
RE_SPAN_ID = re.compile(r"\[?\bD\d+:[\w.]+(?:#s\d+)?\]?")
RE_NIL_CLAIM = re.compile(r"\bnil\b|\bno\s+(?:[\w-]+\s+){0,3}(?:charge|charges|fee|fees)\b|\bnot\s+(?:be\s+)?(?:levied|charged|payable)"
                          r"|\bfree of charge\b|\bwaived\b|\bzero\b", re.IGNORECASE)
RE_NIL_SRC = re.compile(r"\bnil\b|\bno\s+(?:[\w-]+\s+){0,3}(?:charge|charges|fee|fees)\b|\bnot\s+(?:\w+\s+){0,3}(?:levied|charged|payable"
                        r"|permitted)|\bfree\b|\bwaived\b|\bzero\b|\bwithout (?:any )?(?:charge|fee|penalty)", re.IGNORECASE)

WORD_NUMS = {w: float(i) for i, w in enumerate(
    ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"])}
WORD_NUMS.update({"thirty": 30.0, "forty": 40.0, "fifty": 50.0, "sixty": 60.0, "seventy": 70.0, "eighty": 80.0,
                  "ninety": 90.0, "hundred": 100.0, "first": 1.0, "second": 2.0, "third": 3.0, "fourth": 4.0,
                  "fifth": 5.0, "sixth": 6.0, "seventh": 7.0, "eighth": 8.0, "ninth": 9.0, "tenth": 10.0})

Token = tuple[str, float | str]  # ("num", 500.0) | ("pct", 4.0) | ("date", "2025-04-01")


def normalize_text(s: str) -> str:
    """Lowercase; unify rupee spellings; drop commas and whitespace (for containment tests)."""
    s = s.lower().replace("rs.", "₹").replace("rs ", "₹").replace("inr", "₹")
    return re.sub(r"[,\s]+", "", s)


def to_float(s: str) -> float:
    return float(s.replace(",", ""))


def iso_date(y: int, m: int, d: int) -> str:
    return f"{y:04d}-{m:02d}-{d:02d}"


def _dates(text: str) -> tuple[list[str], str]:
    """Extract dates as ISO strings and return the text with them blanked out."""
    found: list[str] = []

    def sub(rx: re.Pattern[str], conv) -> None:
        nonlocal text

        def rep(m: re.Match[str]) -> str:
            iso = conv(m)
            if iso:
                found.append(iso)
                return " "
            return m.group(0)
        text = rx.sub(rep, text)

    sub(RE_ISO, lambda m: iso_date(int(m[1]), int(m[2]), int(m[3])))
    sub(RE_DMY, lambda m: iso_date(int(m[3]), MONTHS[m[2].lower()], int(m[1])))
    sub(RE_MDY, lambda m: iso_date(int(m[3]), MONTHS[m[1].lower()], int(m[2])))
    sub(RE_SLASH, lambda m: iso_date(int(m[3]), int(m[2]), int(m[1])) if 1 <= int(m[2]) <= 12 else None)
    return found, text


def number_tokens(text: str, ignore: str = "") -> list[Token]:
    """Comparable numeric tokens of `text`. Money and plain numbers share kind "num" (so ₹500 == Rs. 500/- == 500)."""
    text = RE_SPAN_ID.sub(" ", text)
    text = RE_CLAUSE_REF.sub(" ", text)
    if ignore:
        text = text.replace(ignore, " ")
    out: list[Token] = []
    dates, text = _dates(text)
    out += [("date", d) for d in dates]

    def take(rx: re.Pattern[str], kind: str, val) -> None:
        nonlocal text

        def rep(m: re.Match[str]) -> str:
            out.append((kind, val(m)))
            return " "
        text = rx.sub(rep, text)

    take(RE_PCT, "pct", lambda m: to_float(m[1]))

    def money(m: re.Match[str]) -> float:
        amt, scale = (m[1], m[2]) if m[1] else (m[3], m[4]) if m[3] else (m[5], None)
        return to_float(amt) * (_SCALE[scale.lower()] if scale else 1.0)
    take(RE_MONEY, "num", money)
    for m in RE_PLAIN.finditer(text):
        try:
            out.append(("num", to_float(m[1].rstrip(","))))
        except ValueError:
            continue
    return out


def source_values(text: str) -> set[Token]:
    """Tokens of a source passage, plus number words (six -> 6) which only ever loosen the match."""
    toks = set(number_tokens(text))
    for w in re.findall(r"[a-z]+", text.lower()):
        if w in WORD_NUMS:
            toks.add(("num", WORD_NUMS[w]))
    return toks


def _eq(a: Token, b: Token) -> bool:
    return a[0] == b[0] and (a[1] == b[1] if isinstance(a[1], str) else abs(float(a[1]) - float(b[1])) < 1e-9)


def missing_numbers(claim: str, context: str, extra: str = "") -> list[str]:
    """Numeric tokens of the claim that the context (or `extra`, e.g. the question) does not contain; [] = all found."""
    ctx = source_values(context) | source_values(extra)
    bad: list[str] = []
    for tok in number_tokens(claim):
        if any(_eq(tok, c) for c in ctx):
            continue
        # a percent may be written bare in a table cell ("4"), and a bare number may be a percent
        if tok[0] == "pct" and any(_eq(("num", tok[1]), c) for c in ctx):
            continue
        bad.append(f"{tok[1]:g}%" if tok[0] == "pct" else f"{tok[1]:g}" if tok[0] == "num" else str(tok[1]))
    if RE_NIL_CLAIM.search(RE_SPAN_ID.sub(" ", claim)) and not RE_NIL_SRC.search(context):
        bad.append("nil / no charge")
    return bad


def parse_value(value_raw: str, value_type: str) -> FactValue:
    """facts-and-subjects.md §3. Raises ValueError when the raw text cannot be parsed for its type."""
    raw = value_raw.strip()
    if value_type == "money":
        m = RE_MONEY.search(raw) or RE_PLAIN.search(raw)
        if not m:
            raise ValueError(f"no amount in {raw!r}")
        toks = [t for t in number_tokens(raw) if t[0] == "num"]
        if not toks:
            raise ValueError(f"no amount in {raw!r}")
        return FactValue(amount=float(toks[0][1]), unit="INR")
    if value_type == "percent":
        m = RE_PCT.search(raw)
        if not m:
            raise ValueError(f"no percent in {raw!r}")
        return FactValue(amount=to_float(m[1]), unit="%")
    if value_type == "duration":
        m = re.search(r"(\d+)\s*(months?|years?|days?|emis?|instal+ments?)", raw, re.IGNORECASE)
        if not m:
            raise ValueError(f"no duration in {raw!r}")
        unit = m[2].lower().rstrip("s")
        return FactValue(amount=float(m[1]), unit="months" if unit == "month" else unit + "s" if unit in ("year", "day") else unit)
    if value_type == "date":
        dates, _ = _dates(raw)
        if not dates:
            raise ValueError(f"no date in {raw!r}")
        return FactValue(date=dates[0])
    if value_type == "bool":
        if RE_NIL_SRC.search(raw) or re.search(r"\bnot\b", raw, re.IGNORECASE):
            return FactValue(flag=False)
        if re.search(r"\b(permitted|allowed|may)\b", raw, re.IGNORECASE):
            return FactValue(flag=True)
        raise ValueError(f"no flag in {raw!r}")
    rng = re.search(rf"({_NUM})\s*(?:to|-|–|—|and)\s*({_NUM})", raw)
    if rng and value_type in ("number", "duration"):
        return FactValue(low=to_float(rng[1]), high=to_float(rng[2]))
    if value_type == "number":
        toks = [t for t in number_tokens(raw) if t[0] == "num"]
        if not toks:
            raise ValueError(f"no number in {raw!r}")
        return FactValue(amount=float(toks[0][1]))
    return FactValue(text=raw)
