"""Calculator (answering.md §5). All arithmetic happens here, in Python; the LLM never sees or produces a result.

Inputs come from two places only:
  * numbers the question itself states (the planner proposes them, we keep one only if it literally appears in the question);
  * verified claims about the documents (each carries its span ids, so every input is cited).
A required input that is missing means no calculation and a "Missing input: ..." line. If the documents give two different
values for one input (a conflict), the result is shown for each value and no single answer is chosen.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass

from core.models import CalcPlan, VerifiedClaim
from core.normalize import RE_NIL_CLAIM, number_tokens

MAX_VARIANTS = 4


def inr(x: float) -> str:
    """Rupee amount with Indian digit grouping: 1234567 -> 12,34,567."""
    neg, n = x < 0, round(abs(x), 2)
    whole, _, frac = f"{n:.2f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    if head:
        head = re.sub(r"(?<=\d)(?=(\d\d)+$)", ",", head)
        whole = f"{head},{tail}"
    out = whole + ("" if frac == "00" else f".{frac}")
    return ("-" if neg else "") + "₹" + out


def num(x: float) -> str:
    return f"{x:,.0f}" if float(x).is_integer() else f"{x:g}"


# ---- the maths (pure, unit-tested) -------------------------------------------------------------------------------

def emi(principal: float, annual_rate_pct: float, months: float) -> tuple[float, list[str]]:
    """Reducing-balance EMI = P·r·(1+r)^n / ((1+r)^n − 1), r = annual rate / 12 / 100. Rounded to the nearest rupee."""
    if principal <= 0 or months <= 0 or annual_rate_pct < 0:
        raise ValueError("loan amount and months must be positive and the rate cannot be negative")
    n = int(months)
    if annual_rate_pct == 0:
        return float(round(principal / n)), [f"No interest, so EMI = {inr(principal)} ÷ {n} = {inr(round(principal / n))}"]
    r = annual_rate_pct / 12 / 100
    growth = (1 + r) ** n
    value = principal * r * growth / (growth - 1)
    return float(round(value)), [
        f"Monthly rate r = {num(annual_rate_pct)} ÷ 12 ÷ 100 = {r:.6f}",
        f"(1 + r)^{n} = {growth:.6f}",
        (f"EMI = {inr(principal)} × {r:.6f} × {growth:.6f} ÷ ({growth:.6f} − 1) = {inr(value)}, "
         f"rounded to {inr(round(value))}"),
    ]


def late_fee_total(fee_per_instalment: float, count: float) -> tuple[float, list[str]]:
    if fee_per_instalment < 0 or count < 0:
        raise ValueError("fee and count cannot be negative")
    total = fee_per_instalment * count
    return float(total), [f"{inr(fee_per_instalment)} × {num(count)} late instalments = {inr(total)}"]


def prepayment_charge(outstanding: float, pct: float | None = None, nil: bool = False) -> tuple[float, list[str]]:
    if outstanding < 0:
        raise ValueError("outstanding amount cannot be negative")
    if nil or not pct:
        return 0.0, ["No prepayment charge applies, so the charge is ₹0"]
    charge = outstanding * pct / 100
    return float(charge), [f"{inr(outstanding)} × {num(pct)}% = {inr(charge)} (GST is not included)"]


# ---- inputs ------------------------------------------------------------------------------------------------------

@dataclass
class Spec:
    name: str  # key in plan.calc.given
    label: str  # plain-language name shown to the reader
    missing: str  # "Missing input: ..." text
    doc: bool  # may come from the documents (else the question only)


SPECS: dict[str, list[Spec]] = {
    "emi": [Spec("principal", "loan amount", "the loan amount", False),
            Spec("annual_rate_pct", "annual interest rate (%)", "the annual interest rate", True),
            Spec("months", "number of months", "the number of months", False)],
    "late_fee_total": [Spec("fee_per_instalment", "late fee per instalment", "the late fee per instalment", True),
                       Spec("count", "number of late instalments", "the number of late instalments", False)],
    "prepayment_charge": [Spec("outstanding", "outstanding amount", "the outstanding loan amount", False),
                          Spec("pct", "prepayment charge (%)", "the prepayment charge that applies", True)],
}
FORMULAS = {"emi": "EMI = P × r × (1 + r)^n ÷ ((1 + r)^n − 1), where r = annual rate ÷ 12 ÷ 100",
            "late_fee_total": "Total late fees = fee per instalment × number of late instalments",
            "prepayment_charge": "Prepayment charge = outstanding amount × percentage ÷ 100"}

RE_RATE = re.compile(r"\binterest\b|\brate\b", re.IGNORECASE)
RE_NOT_RATE = re.compile(r"prepay|foreclos|late|penal|processing|fee|charge|gst", re.IGNORECASE)
RE_PREPAY = re.compile(r"prepay|pre-pay|foreclos", re.IGNORECASE)
RE_LATE = re.compile(r"\blate\b|penal|delay|overdue|default", re.IGNORECASE)


@dataclass
class Found:
    value: float
    span_id: str
    claim_idx: int


def _from_question(question: str, value: float | None) -> float | None:
    """Keep a planner-proposed number only if the question literally contains it."""
    if value is None:
        return None
    nums = {float(t[1]) for t in number_tokens(question) if t[0] in ("num", "pct")}
    return value if any(abs(value - n) < 1e-9 for n in nums) else None


def _doc_values(name: str, claims: list[VerifiedClaim]) -> list[Found]:
    out: list[Found] = []
    for i, c in enumerate(claims):
        if c.verdict == "unsupported" or not c.span_ids:
            continue
        toks = number_tokens(c.text)
        pcts = [float(v) for k, v in toks if k == "pct"]
        nums = [float(v) for k, v in toks if k == "num"]
        value: float | None = None
        if name == "annual_rate_pct" and RE_RATE.search(c.text) and not RE_NOT_RATE.search(c.text) and pcts:
            value = pcts[0]
        elif name == "pct" and RE_PREPAY.search(c.text):
            value = pcts[0] if pcts else (0.0 if RE_NIL_CLAIM.search(c.text) else None)
        elif name == "fee_per_instalment" and RE_LATE.search(c.text) and nums:
            value = nums[0]
        if value is not None:
            out.append(Found(value, c.span_ids[0], i))
    return out


def _compute(kind: str, v: dict[str, float]) -> tuple[float, list[str]]:
    if kind == "emi":
        return emi(v["principal"], v["annual_rate_pct"], v["months"])
    if kind == "late_fee_total":
        return late_fee_total(v["fee_per_instalment"], v["count"])
    return prepayment_charge(v["outstanding"], v["pct"], nil=v["pct"] == 0)


def run(plan: CalcPlan, question: str, claims: list[VerifiedClaim]) -> tuple[dict | None, list[str], set[int]]:
    """Return (calculation or None, missing-input lines, indexes of claims used as inputs)."""
    specs = SPECS.get(plan.kind)
    if not specs:
        return None, [], set()
    fixed: dict[str, tuple[float, str | None]] = {}  # name -> (value, span_id; None = from the question)
    options: dict[str, list[Found]] = {}
    missing: list[str] = []
    for sp in specs:
        q = _from_question(question, plan.given.get(sp.name))
        if q is not None:
            fixed[sp.name] = (q, None)
            continue
        found = list({f.value: f for f in _doc_values(sp.name, claims)}.values()) if sp.doc else []
        if not found:
            missing.append(f"Missing input: {sp.missing}")
        elif len(found) == 1:
            fixed[sp.name] = (found[0].value, found[0].span_id)
            options[sp.name] = found
        else:
            options[sp.name] = found[:MAX_VARIANTS]
    if missing:
        return None, missing, set()

    labels = {sp.name: sp.label for sp in specs}
    inputs: list[dict] = []
    steps: list[str] = []
    for sp in specs:
        if sp.name in fixed:
            val, sid = fixed[sp.name]
            inputs.append({"name": labels[sp.name], "value": val, **({"span_id": sid} if sid else {"source": "question"})})
    varying = [n for n in options if n not in fixed]
    used = {f.claim_idx for fs in options.values() for f in fs}
    try:
        if not varying:
            result, steps = _compute(plan.kind, {n: fixed[n][0] for n in fixed})
            return _out(plan.kind, inputs, steps, result), [], used
        results = []
        for combo in itertools.islice(itertools.product(*(options[n] for n in varying)), MAX_VARIANTS):
            vals = {n: fixed[n][0] for n in fixed} | {n: f.value for n, f in zip(varying, combo)}
            res, st = _compute(plan.kind, vals)
            for n, f in zip(varying, combo):
                inputs.append({"name": f"{labels[n]} (option {len(results) + 1})", "value": f.value, "span_id": f.span_id})
            steps += [f"Option {len(results) + 1}: {s}" for s in st]
            results.append(res)
        return _out(plan.kind, inputs, steps, None, note="The documents disagree on this input, so each value is shown"), [], used
    except (KeyError, ValueError) as e:
        return None, [f"Could not calculate: {e}"], set()


def _out(kind: str, inputs: list[dict], steps: list[str], result: float | None, note: str | None = None) -> dict:
    return {"kind": kind, "formula": FORMULAS[kind], "inputs": inputs, "steps": ([note] if note else []) + steps,
            "result": result, "unit": "INR"}
