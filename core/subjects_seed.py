"""Seed synonyms for subject canonicalisation (facts-and-subjects.md §4). Domain vocabulary, not corpus text."""
from __future__ import annotations

SEED: dict[str, list[str]] = {
    "late_payment_fee": ["late payment fee", "late fee", "penal charge", "penal charges", "delayed payment charge",
                         "penal charge for delayed instalment", "overdue charge", "late payment charge"],
    "prepayment_charge": ["prepayment charge", "foreclosure charge", "pre-closure charge", "part prepayment charge",
                          "prepayment penalty"],
    "processing_fee": ["processing fee", "processing charge", "loan processing fee"],
    "interest_rate": ["interest rate", "rate of interest", "interest"],
    "borrower_age": ["borrower age", "age", "eligibility age", "applicant age", "age of borrower"],
    "loan_amount_max": ["maximum loan amount", "loan amount", "principal amount"],
    "bounce_charge": ["cheque bounce charge", "ecs bounce charge", "bounce charge", "dishonour charge"],
}
