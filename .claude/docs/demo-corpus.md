# Demo corpus spec (ground truth for every test)

`corpus/generate.py` builds six PDFs into `corpus/pdfs/` with **exactly** the text below (wording, numbers, clause numbering
and page breaks matter: `tests/qa.yaml` depends on them). Organisations are fictional (ADR-010).

## Generation rules

- reportlab platypus, A4, margins 2 cm, body 10.5 pt, headings bold 12 pt.
- **Font must contain ₹ (U+20B9).** Register a TTF that has it (DejaVu Sans from `fonts-dejavu-core`, or Noto Sans) and use it
  for all text. After generating, assert `"₹" in fitz.open(pdf)[page].get_text()` for D1 and D2. If the glyph is missing,
  fix the font. Do not swap ₹ for "Rs." silently.
- Filenames: `D1_loan_agreement.pdf`, `D2_schedule_of_charges.pdf`, `D3_amendment_1.pdf`, `D4_amendment_2.pdf`,
  `D5_fcb_circular.pdf`, `D6_faq_scanned.pdf`.
- Each page has a footer "Kestrel Finance Ltd. · Page x of y" (D5: "Financial Conduct Board · Page x of y"). It tests header/footer removal.
- `[PAGE BREAK]` below = an explicit `PageBreak()`. Clause 7.2 is deliberately split across pages 3 → 4 mid-paragraph:
  render it as two Paragraph flowables with a PageBreak between (the second without a clause number).
- D6 is a scan: build it as a normal PDF, rasterise each page with PyMuPDF at 200 dpi, then with Pillow: rotate 0.7°
  (white fill), add Gaussian noise (σ ≈ 6), slight blur (radius 0.6), save as JPEG quality 70. Then create a new PDF with
  `page.insert_image` only, so there is **no text layer**. Assert `page.get_text().strip() == ""`.

---

## D1 — Personal Loan Agreement (digital, 6 pages)

```
PERSONAL LOAN AGREEMENT
Reference No.: KF/PLA/2024
Dated: 15 January 2024 · Effective: 15 January 2024
Between Kestrel Finance Ltd., a non-banking finance company having its registered office at Mumbai (the "Lender"), and the
person named in Schedule I (the "Borrower").

1. Definitions
1.1 "Loan" means the personal loan sanctioned by the Lender to the Borrower under this Agreement.
1.2 "EMI" means the equated monthly instalment payable by the Borrower towards repayment of the Loan.

2. The Loan
2.1 The Lender agrees to lend to the Borrower a principal amount as specified in Schedule I, not exceeding ₹25,00,000 (Rupees Twenty-Five Lakh only).
2.2 The Loan shall be used only for personal purposes and not for any speculative activity.
[PAGE BREAK]
3. Eligibility
3.1 The Borrower must be an individual aged not less than 21 years and not more than 58 years at the time of application.
3.2 The Borrower must have a minimum net monthly income of ₹25,000.

4. Disbursement
4.1 The Loan shall be disbursed to the Borrower's bank account after execution of this Agreement and receipt of the documents required by the Lender.

5. Interest
5.1 The Loan shall carry interest at a floating rate of 13.5% per annum, linked to the Lender's Benchmark Lending Rate.
5.2 Interest shall be computed on a monthly reducing balance basis.
[PAGE BREAK]
6. Repayment
6.1 The Loan shall be repaid in Equated Monthly Instalments (EMIs) over a tenure of 12 to 60 months as specified in Schedule I.
6.2 Each EMI shall be due on the 5th day of every month.

7. Prepayment and Foreclosure
7.1 The Borrower may prepay the Loan in part or in full after payment of the first 6 (six) EMIs, by giving 15 days' written notice to the Lender.
7.2 A prepayment charge of 4% of the principal outstanding shall be payable by the Borrower on any part or full prepayment of the Loan.
[PAGE BREAK]   ← mid-clause; the next paragraph continues 7.2 with no number
The prepayment charge shall be paid together with the prepayment amount and is exclusive of applicable taxes.

8. Default
8.1 If any EMI is not paid on its due date, the Borrower shall pay a late payment fee of ₹500 per instalment delayed.
8.2 Non-payment of three consecutive EMIs shall constitute an event of default.
[PAGE BREAK]
9. Fees and Charges
9.1 The Borrower shall pay a processing fee and other charges as set out in the Lender's Schedule of Charges KF/SOC/2024.

10. Governing Law
10.1 This Agreement shall be governed by the laws of India and the courts at Mumbai shall have exclusive jurisdiction.
[PAGE BREAK]
SCHEDULE I — LOAN DETAILS (table)
| Item | Details |
| Borrower | As per sanction letter |
| Principal amount | As per sanction letter, not exceeding ₹25,00,000 |
| Tenure | 12 to 60 months |
| Rate of interest | 13.5% per annum (floating) |
Signed for Kestrel Finance Ltd. ____________   Borrower ____________
```

## D2 — Schedule of Charges (digital, 1 page, table)

```
SCHEDULE OF CHARGES — PERSONAL LOANS
Reference No.: KF/SOC/2024 · Effective: 15 January 2024
This Schedule applies to Personal Loans under Agreement KF/PLA/2024.

| Charge | Amount | Applicability |
| Processing fee | 2% of the loan amount + GST | At disbursement |
| Late payment fee | ₹750 per instalment | Each EMI not paid on its due date |
| Cheque / ECS bounce charge | ₹590 per instance | Each dishonour |
| Duplicate statement | ₹250 per request | On request |
| Loan cancellation charge | ₹1,000 | Within the cooling-off period |
```

Row numbering: header = row0, so Processing fee = `D2:table1.row1`, Late payment fee = `row2`, Bounce = `row3`,
Duplicate statement = `row4`, Cancellation = `row5`.

## D3 — Amendment No. 1 (digital, 1 page)

```
AMENDMENT No. 1 TO PERSONAL LOAN AGREEMENT KF/PLA/2024
Reference No.: KF/PLA/2024/AMD-1 · Dated: 10 March 2025 · Effective: 1 April 2025

1. With effect from 1 April 2025, Clause 7.2 of the Personal Loan Agreement KF/PLA/2024 shall be substituted by the following:
   "7.2 A prepayment charge of 3% of the principal outstanding shall be payable by the Borrower on any part or full prepayment of the Loan."
2. All other terms and conditions of the Agreement remain unchanged.
```

## D4 — Amendment No. 2 (digital, 1 page)

```
AMENDMENT No. 2 TO PERSONAL LOAN AGREEMENT KF/PLA/2024
Reference No.: KF/PLA/2024/AMD-2 · Dated: 1 December 2025 · Effective: 1 January 2026

1. In supersession of Amendment No. 1 (KF/PLA/2024/AMD-1), with effect from 1 January 2026, Clause 7.2 of the Personal Loan
   Agreement KF/PLA/2024 shall be substituted by the following:
   "7.2 No prepayment charge shall be levied on floating rate loans sanctioned to individual borrowers. For fixed rate loans,
   a prepayment charge of 2% of the principal outstanding shall be payable."
2. All other terms and conditions of the Agreement remain unchanged.
```

## D5 — FCB circular (digital, 1 page)

```
FINANCIAL CONDUCT BOARD
Circular No. FCB/2025/17 · Dated: 15 October 2025 · Effective: 1 November 2025
To: All Regulated Lenders
Subject: Fair practices on penal charges in loan accounts

1. Regulated lenders shall not levy penal charges for delayed payment of an instalment exceeding ₹600 per instalment.
2. Penal charges shall not be added to the rate of interest or capitalised.
3. All regulated lenders shall revise their schedules of charges to comply with this circular with effect from 1 November 2025.
```

## D6 — Customer FAQ (scanned, 1 page, no text layer)

```
KESTREL FINANCE — PERSONAL LOAN: FREQUENTLY ASKED QUESTIONS
Updated: June 2025

Q1. Who can apply?
Salaried and self-employed individuals aged 21 to 60 years can apply for a Kestrel Personal Loan.
Q2. What is the maximum loan amount?
You can borrow up to ₹25 lakh.
Q3. How is interest charged?
Interest is charged on a monthly reducing balance.
Q4. Can I prepay my loan?
Yes, after paying 6 EMIs. Charges are as per your loan agreement.
Q5. What documents do I need?
PAN, Aadhaar and salary slips for the last 3 months.
```

Clause ids: `D6:p1.q1` … `D6:p1.q5`. Effective date: 2025-06-01 (register normalises "June 2025" to the 1st).

---

## Expected derived data (assert in tests)

| What | Expected |
|---|---|
| Version timeline `D1:7.2` | v0 D1:7.2 [2024-01-15, 2025-04-01) · v1 D3:1 [2025-04-01, 2026-01-01) · v2 D4:1 [2026-01-01, ∞) |
| Conflicts | C1 late_payment_fee D1:8.1 vs D2:table1.row2 (numeric) · C2 late_payment_fee D2:table1.row2 vs D5:1 (rule, from 2025-11-01) · C3 borrower_age D1:3.1 vs D6:p1.q1 (eligibility, from 2025-06-01) |
| Not conflicts | anything between versions of D1:7.2 · D1:8.1 ₹500 vs D5 cap ₹600 · D1:2.1 ₹25,00,000 vs D6 ₹25 lakh · D1:3.1 min age 21 vs D6 21 |
| OCR | D6 `has_ocr=1`; `D6:p1.q1` text contains "21" and "60" |
