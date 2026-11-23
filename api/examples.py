"""Example questions for the empty chat. Demo-corpus specific, so they live in the app layer (ADR-013, ADR-017)."""
from __future__ import annotations

EXAMPLES = [
    {"title": "Compare documents", "question": "What fees apply if I pay an EMI late?",
     "hint": "Finds where the documents disagree"},
    {"title": "What applies today?", "question": "What is the prepayment charge today for a floating-rate loan to an individual?",
     "hint": "Follows amendments to the rule in force"},
    {"title": "Ask something not covered", "question": "What is the GST rate on the processing fee?",
     "hint": "Shows how missing proof is handled"},
    {"title": "Work out an amount", "question": "What would my EMI be on a ₹5,00,000 loan at the agreement's interest rate for 36 months?",
     "hint": "Shows the working, step by step"},
]
