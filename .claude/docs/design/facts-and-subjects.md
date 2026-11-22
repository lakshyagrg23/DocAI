# Design: Fact extraction and subject canonicalisation (ingest time)

Covers the basis of FR-8 (conflicts) and the version checks in FR-9. Code: `core/ingest/{extract,subjects}.py`, `core/normalize.py`.

## 1. Which clauses get extraction

All clauses with `kind != definition` and text containing at least one of: a digit, `%`, `₹|Rs|INR`, an age/eligibility
word, or a modal verb (`shall|must|may|not permitted|prohibited|no .* shall`). Batch up to 6 clauses per LLM call;
Ollama serves `OLLAMA_NUM_PARALLEL=4` requests at once, so use a thread pool of 4.

## 2. LLM extraction (prompt `extract_facts.md`, guided JSON)

Input: clauses with their spans, formatted as `[span_id] text`, plus the doc title and type.
Output: `{"facts": [ExtractedFact, ...], "amendments": [AmendmentDirective, ...]}` (see data-model.md).
Amendment directives are requested in the same call to save time; their handling is in amendments.md.

Prompt rules (write them into the prompt verbatim):
- Extract only what the text states. One fact per (subject, attribute) per span. `value_raw` must be copied exactly from the span.
- `subject` = the thing regulated, in 2–5 plain words ("late payment fee", "prepayment charge", "borrower age",
  "interest rate", "processing fee", "penal charge for delayed instalment").
- `op`: `eq` (is X), `max` (not exceeding / up to / capped at), `min` (at least / not less than), `range` (between A and B; aged 21 to 58),
  `bool` (permitted / not permitted / nil / no charge → `value_type=bool` with `flag`; "nil"/"no charge" → money eq 0 **and** note it in `condition_text`).
- `scope`: only qualifiers stated in the text: `rate_type` (floating|fixed), `borrower` (individual|non_individual), `product` (personal_loan, …),
  `per` (instalment|instance|month|annum).
- Amounts in Indian format (`5,00,000`, `₹25 lakh`) stay verbatim in `value_raw`; normalisation is done in code.

## 3. Code-side normalisation and validation (`core/normalize.py`)

`parse_value(value_raw, value_type) -> FactValue`:
- money: strip `₹`, `Rs.`, `Rs`, `INR`, `/-`, commas; `lakh` × 1e5, `crore` × 1e7; unit `INR`.
- percent: `(\d+(?:\.\d+)?)\s*(?:%|per\s*cent|percent)`; unit `%`.
- duration: `(\d+)\s*(months?|years?|days?|EMIs?|instalments?)`.
- range: `(\d+)\s*(?:to|-|–|and)\s*(\d+)` → low/high (ages, tenures).
- date: dateparser, DMY.
- bool: `nil|no .*charge|not .*(levied|permitted|payable)` → flag False (charge not applicable); `permitted|allowed|may` → True.

**Validation (drop the fact if any fails):** the `span_id` exists and belongs to one of the given clauses;
`normalize_text(value_raw)` occurs in `normalize_text(span.text)` (lowercase, unify ₹/Rs., remove commas and spaces);
`parse_value` succeeds. Log dropped facts with the reason to `logs/ingest.log`.

The same `parse_value` / number-token extraction is reused by the verifier (answering.md §Verify b), so the two can't disagree.

## 4. Subject canonicalisation (`subjects.py`)

Goal: "late payment fee" (D1), "Late payment fee" (D2 table), "penal charges for delayed payment of instalments" (D5) → one subject.

1. Key candidate: `slug(subject)` (lowercase, non-alphanumerics → `_`, drop stop-words such as "the", "of", "for", "on").
2. **Seed synonyms** (in `core/subjects_seed.py`, checked first):
   ```python
   SEED = {
     "late_payment_fee": ["late payment fee","late fee","penal charge","penal charges","delayed payment charge",
                          "penal charge for delayed instalment","overdue charge","late payment charge"],
     "prepayment_charge": ["prepayment charge","foreclosure charge","pre-closure charge","part prepayment charge","prepayment penalty"],
     "processing_fee": ["processing fee","processing charge","loan processing fee"],
     "interest_rate": ["interest rate","rate of interest","interest"],
     "borrower_age": ["borrower age","age","eligibility age","applicant age","age of borrower"],
     "loan_amount_max": ["maximum loan amount","loan amount","principal amount"],
     "bounce_charge": ["cheque bounce charge","ecs bounce charge","bounce charge","dishonour charge"],
   }
   ```
   A fuzzy match (rapidfuzz `token_set_ratio ≥ 90`) against any alias → that subject.
3. Otherwise embed the subject label (`/embed`); cosine against `subjects.npy`. If max ≥ `SUBJECT_SIM_MIN`, ask the LLM
   (prompt `same_subject.md`, JSON `{"same": bool}`): "Do these two refer to the same charge/condition in a loan context?"
   Yes → merge (append alias). No / below threshold → create a new subject.
4. Attribute normalisation: map to `amount | rate | age | tenure | date | permitted | other` by value_type and subject.

## Tests

- `parse_value("₹ 5,00,000", "money").amount == 500000`; `"Rs. 750/-" → 750`; `"₹25 lakh" → 2_500_000`; `"13.5% p.a." → 13.5`.
- `"aged not less than 21 years and not more than 58 years"` handled as range 21–58 (the LLM may emit min + max facts instead;
  conflict logic must handle both forms; see contradictions.md).
- After ingesting D1, D2 and D5: facts from D1:8.1, the D2 late-fee row and D5:1 share `subject_id == "late_payment_fee"`.
