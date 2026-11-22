"""Pure contradiction rules (contradictions.md §1-§2). No DB, no LLM: facts in, verdict out."""
from __future__ import annotations

from dataclasses import dataclass, field

from core.models import FactValue

ELIGIBILITY_SUBJECTS = {"borrower_age", "borrower_income", "net_monthly_income"}
EPS = 1e-6
PER_EQUIVALENT = {"instalment": "instalment", "installment": "instalment", "instance": "instalment",
                  "emi": "instalment", "month": "month", "annum": "annum", "year": "annum"}


@dataclass
class FactView:
    fact_id: str
    clause_id: str
    span_id: str
    subject_id: str
    attribute: str
    op: str  # eq | max | min | range | bool
    value_type: str
    value: FactValue
    scope: dict[str, str] = field(default_factory=dict)
    version_key: str = ""
    start: str | None = None  # validity interval [start, end)
    end: str | None = None
    label: str = ""  # "Personal Loan Agreement, cl. 8.1": used in explanations
    raw: str = ""


@dataclass
class ConflictVerdict:
    type: str  # numeric | rule | eligibility | date | text
    severity: str
    explanation: str
    differing: dict[str, list]  # {"a": [...], "b": [...]}: the values that disagree on each side
    overlap_from: str | None = None
    overlap_to: str | None = None


# ---- compatibility ------------------------------------------------------------------

def _per(scope: dict[str, str]) -> str | None:
    p = scope.get("per")
    return PER_EQUIVALENT.get(p.strip().lower(), p.strip().lower()) if p else None


def scopes_compatible(a: dict[str, str], b: dict[str, str]) -> bool:
    """Keys present in both must agree; a key present in only one side is fine (general vs specific still conflicts)."""
    for k in set(a) & set(b):
        if k == "per":
            continue
        if str(a[k]).strip().lower() != str(b[k]).strip().lower():
            return False
    pa, pb = _per(a), _per(b)
    return pa is None or pb is None or pa == pb


def overlap(a: FactView, b: FactView) -> tuple[str | None, str | None] | None:
    """Intersection of two [start, end) intervals (None = open). Returns None when empty."""
    start = max((x for x in (a.start, b.start) if x), default=None)
    ends = [x for x in (a.end, b.end) if x]
    end = min(ends) if ends else None
    if start is not None and end is not None and start >= end:
        return None
    return start, end


def merge_ranges(facts: list[FactView]) -> list[FactView]:
    """A min and a max fact on the same clause/attribute become one range fact (age >= 21 and <= 58 -> 21-58)."""
    groups: dict[tuple[str, str, str], list[FactView]] = {}
    for f in facts:
        groups.setdefault((f.clause_id, f.subject_id, f.attribute), []).append(f)
    out: list[FactView] = []
    for g in groups.values():
        mins = [f for f in g if f.op == "min" and f.value.amount is not None]
        maxs = [f for f in g if f.op == "max" and f.value.amount is not None]
        if mins and maxs:
            lo, hi = mins[0], maxs[0]
            merged = FactView(lo.fact_id, lo.clause_id, lo.span_id, lo.subject_id, lo.attribute, "range", lo.value_type,
                              FactValue(low=lo.value.amount, high=hi.value.amount, unit=lo.value.unit),
                              {**hi.scope, **lo.scope}, lo.version_key, lo.start, lo.end, lo.label,
                              f"{lo.raw} / {hi.raw}")
            out.append(merged)
            out += [f for f in g if f not in (lo, hi)]
        else:
            out += g
    return out


# ---- formatting ---------------------------------------------------------------------

def _num(x: float) -> str:
    return f"{x:,.0f}" if float(x).is_integer() else f"{x:g}"


def fmt(f: FactView) -> str:
    v = f.value
    per = _per(f.scope)
    suffix = f" per {per}" if per else ""
    if f.op == "range" or (v.low is not None and v.high is not None):
        return f"{_num(v.low or 0)}-{_num(v.high or 0)}"
    if v.flag is not None:
        return "no charge / not permitted" if v.flag is False else "permitted"
    if v.date:
        return v.date
    if v.amount is None:
        return f.raw
    if f.value_type == "money":
        return f"₹{_num(v.amount)}{suffix}"
    if f.value_type == "percent":
        return f"{_num(v.amount)}%{suffix}"
    return f"{_num(v.amount)}{(' ' + v.unit) if v.unit else ''}{suffix}"


def _amount_kind(f: FactView) -> str:
    return f.value_type if f.value_type in ("money", "percent", "duration") else "number"


# ---- comparison ---------------------------------------------------------------------

def compare(a: FactView, b: FactView) -> ConflictVerdict | None:
    """Return a verdict when the two facts contradict each other, else None. Does not check scope/overlap."""
    if (a.op, b.op) in (("max", "eq"), ("min", "eq"), ("eq", "bool"), ("eq", "range")):
        v = compare(b, a)  # normalise orientation, then swap the sides back
        if v is None:
            return None
        v.differing = {"a": v.differing["b"], "b": v.differing["a"]}
        return v
    kind = "eligibility" if (a.subject_id in ELIGIBILITY_SUBJECTS or a.attribute == "age") else None
    av, bv = a.value, b.value
    both_amounts = av.amount is not None and bv.amount is not None and _amount_kind(a) == _amount_kind(b)

    def mk(type_: str, text: str, da: list, db: list, severity: str | None = None) -> ConflictVerdict:
        sev = severity or ("high" if type_ in ("numeric", "rule", "eligibility") and
                           a.value_type in ("money", "percent", "number", "duration", "bool") else "medium")
        o = overlap(a, b)
        return ConflictVerdict(type_, sev, text, {"a": da, "b": db}, o[0] if o else None, o[1] if o else None)

    if a.op == "eq" and b.op == "eq" and both_amounts:
        if av.unit != bv.unit and a.value_type == "duration":
            return None
        if abs(av.amount - bv.amount) > EPS:  # type: ignore[operator]
            return mk(kind or "numeric", f"{fmt(a)} ({a.label}) vs {fmt(b)} ({b.label})", [av.amount], [bv.amount])
        return None
    if a.op == "eq" and b.op == "max" and both_amounts:
        if av.amount > bv.amount + EPS:  # type: ignore[operator]
            return mk("rule", f"{fmt(a)} ({a.label}) exceeds the {fmt(b)} cap ({b.label})", [av.amount], [bv.amount])
        return None
    if a.op == "eq" and b.op == "min" and both_amounts:
        if av.amount < bv.amount - EPS:  # type: ignore[operator]
            return mk("rule", f"{fmt(a)} ({a.label}) is below the {fmt(b)} minimum ({b.label})", [av.amount], [bv.amount])
        return None
    if a.op == "range" and b.op == "range" and None not in (av.low, av.high, bv.low, bv.high):
        da = [x for x, y in ((av.low, bv.low), (av.high, bv.high)) if abs(x - y) > EPS]  # type: ignore[operator]
        db = [y for x, y in ((av.low, bv.low), (av.high, bv.high)) if abs(x - y) > EPS]  # type: ignore[operator]
        if da:
            return mk(kind or "numeric", f"{fmt(a)} ({a.label}) vs {fmt(b)} ({b.label})", da, db)
        return None
    if a.op == "range" and b.op == "eq" and av.low is not None and av.high is not None and bv.amount is not None:
        if not av.low - EPS <= bv.amount <= av.high + EPS:
            return mk(kind or "numeric", f"{fmt(b)} ({b.label}) is outside {fmt(a)} ({a.label})", [av.low, av.high], [bv.amount])
        return None
    if a.op == "bool" and av.flag is False and b.op == "eq" and bv.amount is not None and bv.amount > 0:
        return mk("rule", f"no charge ({a.label}) vs {fmt(b)} ({b.label})", ["nil"], [bv.amount])
    if a.op == "bool" and b.op == "bool" and av.flag is not None and bv.flag is not None and av.flag != bv.flag:
        return mk("rule", f"{fmt(a)} ({a.label}) vs {fmt(b)} ({b.label})", [av.flag], [bv.flag])
    if a.value_type == "date" and b.value_type == "date" and a.attribute == b.attribute and av.date and bv.date:
        if av.date != bv.date:
            return mk("date", f"{av.date} ({a.label}) vs {bv.date} ({b.label})", [av.date], [bv.date], "medium")
        return None
    return None  # max/max, min/min, mixed kinds and text pairs (the judge handles text) are not code conflicts


def candidate(a: FactView, b: FactView) -> bool:
    """Contradictions.md §1: different clause and different version key, compatible scope, overlapping validity."""
    return (a.clause_id != b.clause_id and a.version_key != b.version_key
            and scopes_compatible(a.scope, b.scope) and overlap(a, b) is not None)
