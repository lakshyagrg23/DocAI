"""Language helpers (answering.md §6): detection, Devanagari digits, fixed Hindi strings, the number guard.

Design: the whole answering pipeline runs in English (the HHEM verifier, the number/quote checks and the document
text are English). Hindi is a thin layer on both ends: the question is translated by the planner call (no extra
model call), and the verified claims are translated once at the end, guarded by `same_numbers`.
Everything fixed (labels, formulas, abstain text) is a dictionary here, so it costs no model time and cannot drift.
"""
from __future__ import annotations

import re

LANGS = ("en", "hi")
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_NUM = re.compile(r"\d+(?:\.\d+)?")
HI_RATIO_MIN = 0.30  # Devanagari share of letters that makes a text "Hindi"


def to_ascii_digits(text: str) -> str:
    """Devanagari digits -> ASCII (१३.५% -> 13.5%), so every downstream number check sees the same digits."""
    return text.translate(_DIGITS)


def detect_language(text: str) -> str:
    letters = _LETTER.findall(text)
    if not letters:
        return "en"
    return "hi" if len(DEVANAGARI.findall(text)) / len(letters) > HI_RATIO_MIN else "en"


def resolve_language(chat_language: str | None, question: str) -> str:
    """Answer language: the chat's explicit setting wins; 'auto' (or anything else) follows the question."""
    if chat_language in LANGS:
        return chat_language
    return detect_language(question)


def numbers_in(text: str) -> list[str]:
    """Numbers as canonical strings, ignoring digit grouping commas and the digit script."""
    t = re.sub(r"(?<=\d),(?=\d)", "", to_ascii_digits(text))
    return sorted(str(float(m)) for m in _NUM.findall(t))


def same_numbers(english: str, translated: str) -> bool:
    """Number guard: a translation may not add, drop or change a number."""
    return numbers_in(english) == numbers_in(translated)


# ---- fixed Hindi strings (kept next to the English they translate) ------------------------------------------------

ABSTAIN = {"en": "I don't have proof for this in the uploaded documents.",
           "hi": "अपलोड किए गए दस्तावेज़ों में इसका कोई प्रमाण मुझे नहीं मिला।"}

# calculator: plain-language input names, formulas and notes (core/answer/calc.py produces the English)
HI_CALC: dict[str, str] = {
    "loan amount": "ऋण राशि",
    "annual interest rate (%)": "वार्षिक ब्याज दर (%)",
    "number of months": "महीनों की संख्या",
    "late fee per instalment": "प्रति किस्त विलंब शुल्क",
    "number of late instalments": "देरी से भरी किस्तों की संख्या",
    "outstanding amount": "बकाया राशि",
    "prepayment charge (%)": "पूर्व-भुगतान शुल्क (%)",
    "EMI = P × r × (1 + r)^n ÷ ((1 + r)^n − 1), where r = annual rate ÷ 12 ÷ 100":
        "ईएमआई = P × r × (1 + r)^n ÷ ((1 + r)^n − 1), जहाँ r = वार्षिक दर ÷ 12 ÷ 100",
    "Total late fees = fee per instalment × number of late instalments":
        "कुल विलंब शुल्क = प्रति किस्त शुल्क × देरी से भरी किस्तों की संख्या",
    "Prepayment charge = outstanding amount × percentage ÷ 100":
        "पूर्व-भुगतान शुल्क = बकाया राशि × प्रतिशत ÷ 100",
    "The documents disagree on this input, so each value is shown":
        "इस इनपुट पर दस्तावेज़ों में मतभेद है, इसलिए हर मान दिखाया गया है",
}
_OPTION = re.compile(r"^(.*) \(option (\d+)\)$")


def hi_calc_text(text: str) -> str | None:
    """Hindi form of a fixed calculator string (input name, formula, note); None when there is none."""
    if text in HI_CALC:
        return HI_CALC[text]
    m = _OPTION.match(text)
    if m and m[1] in HI_CALC:
        return f"{HI_CALC[m[1]]} (विकल्प {m[2]})"
    return None


def localize_calculation(calc: dict | None, lang: str) -> dict | None:
    """Add `*_local` fields next to the English calculator output. Numbers and step arithmetic are untouched."""
    if not calc or lang != "hi":
        return calc
    out = dict(calc)
    if (f := hi_calc_text(calc.get("formula", ""))):
        out["formula_local"] = f
    out["inputs"] = [{**i, **({"name_local": n} if (n := hi_calc_text(i.get("name", ""))) else {})}
                     for i in calc.get("inputs", [])]
    out["steps_local"] = [hi_calc_text(s) or s for s in calc.get("steps", [])]
    return out
