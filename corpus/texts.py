"""Exact demo-corpus text (.claude/docs/demo-corpus.md). Fictional organisations only (ADR-010).

Each document is a list of pages; each page is a list of blocks:
  ("title", text) | ("h", text) | ("p", text) | ("table", rows, col_widths_cm)
"""
from __future__ import annotations

Block = tuple
Page = list[Block]

D1: list[Page] = [
    [
        ("title", "PERSONAL LOAN AGREEMENT"),
        ("p", "Reference No.: KF/PLA/2024"),
        ("p", "Dated: 15 January 2024 · Effective: 15 January 2024"),
        ("p", 'Between Kestrel Finance Ltd., a non-banking finance company having its registered office at Mumbai '
              '(the "Lender"), and the person named in Schedule I (the "Borrower").'),
        ("h", "1. Definitions"),
        ("p", '1.1 "Loan" means the personal loan sanctioned by the Lender to the Borrower under this Agreement.'),
        ("p", '1.2 "EMI" means the equated monthly instalment payable by the Borrower towards repayment of the Loan.'),
        ("h", "2. The Loan"),
        ("p", "2.1 The Lender agrees to lend to the Borrower a principal amount as specified in Schedule I, "
              "not exceeding ₹25,00,000 (Rupees Twenty-Five Lakh only)."),
        ("p", "2.2 The Loan shall be used only for personal purposes and not for any speculative activity."),
    ],
    [
        ("h", "3. Eligibility"),
        ("p", "3.1 The Borrower must be an individual aged not less than 21 years and not more than 58 years "
              "at the time of application."),
        ("p", "3.2 The Borrower must have a minimum net monthly income of ₹25,000."),
        ("h", "4. Disbursement"),
        ("p", "4.1 The Loan shall be disbursed to the Borrower's bank account after execution of this Agreement "
              "and receipt of the documents required by the Lender."),
        ("h", "5. Interest"),
        ("p", "5.1 The Loan shall carry interest at a floating rate of 13.5% per annum, linked to the Lender's "
              "Benchmark Lending Rate."),
        ("p", "5.2 Interest shall be computed on a monthly reducing balance basis."),
    ],
    [
        ("h", "6. Repayment"),
        ("p", "6.1 The Loan shall be repaid in Equated Monthly Instalments (EMIs) over a tenure of 12 to 60 months "
              "as specified in Schedule I."),
        ("p", "6.2 Each EMI shall be due on the 5th day of every month."),
        ("h", "7. Prepayment and Foreclosure"),
        ("p", "7.1 The Borrower may prepay the Loan in part or in full after payment of the first 6 (six) EMIs, "
              "by giving 15 days' written notice to the Lender."),
        ("p", "7.2 A prepayment charge of 4% of the principal outstanding shall be payable by the Borrower on any "
              "part or full prepayment of the Loan."),
    ],
    [
        # continuation of 7.2 with no clause number (mid-clause page break)
        ("p", "The prepayment charge shall be paid together with the prepayment amount and is exclusive of "
              "applicable taxes."),
        ("h", "8. Default"),
        ("p", "8.1 If any EMI is not paid on its due date, the Borrower shall pay a late payment fee of ₹500 "
              "per instalment delayed."),
        ("p", "8.2 Non-payment of three consecutive EMIs shall constitute an event of default."),
    ],
    [
        ("h", "9. Fees and Charges"),
        ("p", "9.1 The Borrower shall pay a processing fee and other charges as set out in the Lender's Schedule "
              "of Charges KF/SOC/2024."),
        ("h", "10. Governing Law"),
        ("p", "10.1 This Agreement shall be governed by the laws of India and the courts at Mumbai shall have "
              "exclusive jurisdiction."),
    ],
    [
        ("h", "SCHEDULE I — LOAN DETAILS"),
        ("table", [["Item", "Details"],
                   ["Borrower", "As per sanction letter"],
                   ["Principal amount", "As per sanction letter, not exceeding ₹25,00,000"],
                   ["Tenure", "12 to 60 months"],
                   ["Rate of interest", "13.5% per annum (floating)"]], [5, 11]),
        ("p", "Signed for Kestrel Finance Ltd. ____________   Borrower ____________"),
    ],
]

D2: list[Page] = [[
    ("title", "SCHEDULE OF CHARGES — PERSONAL LOANS"),
    ("p", "Reference No.: KF/SOC/2024 · Effective: 15 January 2024"),
    ("p", "This Schedule applies to Personal Loans under Agreement KF/PLA/2024."),
    ("table", [["Charge", "Amount", "Applicability"],
               ["Processing fee", "2% of the loan amount + GST", "At disbursement"],
               ["Late payment fee", "₹750 per instalment", "Each EMI not paid on its due date"],
               ["Cheque / ECS bounce charge", "₹590 per instance", "Each dishonour"],
               ["Duplicate statement", "₹250 per request", "On request"],
               ["Loan cancellation charge", "₹1,000", "Within the cooling-off period"]], [5.5, 5.5, 6]),
]]

D3: list[Page] = [[
    ("title", "AMENDMENT No. 1 TO PERSONAL LOAN AGREEMENT KF/PLA/2024"),
    ("p", "Reference No.: KF/PLA/2024/AMD-1 · Dated: 10 March 2025 · Effective: 1 April 2025"),
    ("p", "1. With effect from 1 April 2025, Clause 7.2 of the Personal Loan Agreement KF/PLA/2024 shall be "
          "substituted by the following:"),
    ("p", '"7.2 A prepayment charge of 3% of the principal outstanding shall be payable by the Borrower on any '
          'part or full prepayment of the Loan."'),
    ("p", "2. All other terms and conditions of the Agreement remain unchanged."),
]]

D4: list[Page] = [[
    ("title", "AMENDMENT No. 2 TO PERSONAL LOAN AGREEMENT KF/PLA/2024"),
    ("p", "Reference No.: KF/PLA/2024/AMD-2 · Dated: 1 December 2025 · Effective: 1 January 2026"),
    ("p", "1. In supersession of Amendment No. 1 (KF/PLA/2024/AMD-1), with effect from 1 January 2026, Clause 7.2 "
          "of the Personal Loan Agreement KF/PLA/2024 shall be substituted by the following:"),
    ("p", '"7.2 No prepayment charge shall be levied on floating rate loans sanctioned to individual borrowers. '
          'For fixed rate loans, a prepayment charge of 2% of the principal outstanding shall be payable."'),
    ("p", "2. All other terms and conditions of the Agreement remain unchanged."),
]]

D5: list[Page] = [[
    ("title", "FINANCIAL CONDUCT BOARD"),
    ("p", "Circular No. FCB/2025/17 · Dated: 15 October 2025 · Effective: 1 November 2025"),
    ("p", "To: All Regulated Lenders"),
    ("p", "Subject: Fair practices on penal charges in loan accounts"),
    ("p", "1. Regulated lenders shall not levy penal charges for delayed payment of an instalment exceeding "
          "₹600 per instalment."),
    ("p", "2. Penal charges shall not be added to the rate of interest or capitalised."),
    ("p", "3. All regulated lenders shall revise their schedules of charges to comply with this circular with "
          "effect from 1 November 2025."),
]]

D6: list[Page] = [[
    ("title", "KESTREL FINANCE — PERSONAL LOAN: FREQUENTLY ASKED QUESTIONS"),
    ("p", "Updated: June 2025"),
    ("p", "<b>Q1. Who can apply?</b>"),
    ("p", "Salaried and self-employed individuals aged 21 to 60 years can apply for a Kestrel Personal Loan."),
    ("p", "<b>Q2. What is the maximum loan amount?</b>"),
    ("p", "You can borrow up to ₹25 lakh."),
    ("p", "<b>Q3. How is interest charged?</b>"),
    ("p", "Interest is charged on a monthly reducing balance."),
    ("p", "<b>Q4. Can I prepay my loan?</b>"),
    ("p", "Yes, after paying 6 EMIs. Charges are as per your loan agreement."),
    ("p", "<b>Q5. What documents do I need?</b>"),
    ("p", "PAN, Aadhaar and salary slips for the last 3 months."),
]]

FILES = {
    "D1_loan_agreement.pdf": (D1, "Kestrel Finance Ltd."),
    "D2_schedule_of_charges.pdf": (D2, "Kestrel Finance Ltd."),
    "D3_amendment_1.pdf": (D3, "Kestrel Finance Ltd."),
    "D4_amendment_2.pdf": (D4, "Kestrel Finance Ltd."),
    "D5_fcb_circular.pdf": (D5, "Financial Conduct Board"),
    "D6_faq_scanned.pdf": (D6, "Kestrel Finance Ltd."),
}
