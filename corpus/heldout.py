"""Held-out generalisation corpus (ADR-013): differently formatted fictional documents, never used to tune prompts or rules.

Formats differ from the demo corpus on purpose: "Article / Section 1.01" numbering, an unnumbered notice, and a fee table with
merged cells. It has its own planted conflict (ATM limit) and its own amendment (monthly maintenance fee).
Run: python corpus/heldout.py   ->  corpus/heldout/H1..H3.pdf
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus.generate import build_pdf

OUT = Path(__file__).resolve().parent / "heldout"
FOOTER = "Marlin Savings Cooperative Ltd."

H1 = [[
    ("title", "SAVINGS ACCOUNT TERMS AND CONDITIONS"),
    ("p", "Document No. MSC-SA-2025 · Issued 1 July 2025 · In force from 1 July 2025"),
    ("p", 'These terms apply between Marlin Savings Cooperative Ltd. (the "Society") and every holder of a savings account.'),
    ("h", "ARTICLE 1. ACCOUNT OPENING"),
    ("p", "Section 1.01 An applicant must be an individual aged 18 years or more."),
    ("p", "Section 1.02 The minimum opening deposit is ₹1,000."),
    ("h", "ARTICLE 2. FEES AND BALANCES"),
    ("p", "Section 2.01 A monthly maintenance fee of ₹150 is charged on every savings account."),
    ("p", ("Section 2.02 The average monthly balance to be maintained is ₹10,000. A shortfall fee of ₹75 applies "
           "when the average balance falls below that amount.")),
], [
    ("p", "Section 2.03 Interest is paid at 3.5% per annum on the daily closing balance and is credited every quarter."),
    ("h", "ARTICLE 3. WITHDRAWALS AND CLOSURE"),
    ("p", "Section 3.01 Cash withdrawals at ATMs are limited to ₹25,000 per day."),
    ("p", "Section 3.02 Closing the account within 90 days of opening attracts a closure fee of ₹200."),
]]

H2 = [[
    ("title", "NOTICE TO SAVINGS ACCOUNT CUSTOMERS"),
    ("p", "Notice dated 12 February 2026"),
    ("p", ("Marlin Savings Cooperative Ltd. informs all savings account customers that, with effect from 1 March 2026, "
           "the monthly maintenance fee under Section 2.01 of the Savings Account Terms and Conditions "
           "(Document No. MSC-SA-2025) is revised to ₹100 per month.")),
    ("p", "All other provisions of the Savings Account Terms and Conditions remain unchanged."),
    ("p", "Customers who prefer to stop paper statements may do so at any branch."),
]]

H3 = [[
    ("title", "TARIFF OF SERVICE CHARGES: SAVINGS ACCOUNTS"),
    ("p", "Tariff in force from 1 July 2025"),
    ("table", [["Category", "Service", "Charge"],
               ["Cash services", "ATM cash withdrawal limit per day", "₹40,000"],
               ["", "Cash deposit at a branch", "No charge"],
               ["Account services", "Duplicate statement", "₹50 per statement"],
               ["", "Cheque book of 25 leaves", "₹100"]],
     [4.0, 8.0, 5.0], [((0, 1), (0, 2)), ((0, 3), (0, 4))]),
]]

FILES = {"H1_savings_terms.pdf": H1, "H2_customer_notice.pdf": H2, "H3_tariff.pdf": H3}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, pages in FILES.items():
        build_pdf(OUT / name, pages, FOOTER)
        print("wrote", OUT / name)


if __name__ == "__main__":
    main()
