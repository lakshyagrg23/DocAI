# Design: Answering — draft → verify → gate → assemble (+ calculator, Hindi)

Covers FR-4, FR-5, FR-6, FR-7, FR-10, FR-12, FR-13. Code: `core/answer/{draft,verify,gate,calc,translate,assemble}.py`.
Entry point: `assemble.answer(chat_id, question, on_stage=callback) -> AnswerJSON` (data-model.md).

## 0. Flow

```
lang detect → (hi: translate question) → plan (retrieval.md) → retrieve + expand → evidence pack
→ draft (LLM) → verify each claim → gate → conflicts / chains / calc → faithfulness → (hi: translate claims) → save + log
```

`on_stage` is called with "Planning", "Retrieving", "Drafting", "Verifying N claims", "Checking conflicts", "Done".

## 1. Draft (`draft.py`, prompt `draft.md`, guided JSON → `Draft`)

System prompt rules (put them in the prompt verbatim):
1. Use ONLY the evidence spans below. Do not use outside knowledge.
2. Write short atomic claims: one fact per claim, at most 8 claims.
3. Every claim must cite ≥ 1 span id exactly as given, e.g. `D1:8.1#s1`.
4. Copy numbers, amounts, percentages and dates exactly as they appear in the evidence. Never calculate.
5. If two spans state different values for the same thing, write one claim per source, each citing its own span.
   Do not choose between them.
6. If the evidence does not answer the question or a part of it, do not guess: add a short description of the missing
   information to `missing`.
7. For history questions, state the period the rule applied ("From 1 April 2025 to 31 December 2025, …").
8. For calculation questions, do not compute; return the input values as claims with `kind = "calc_input"`.

User message: the question (English), the as-of date, and the evidence pack (retrieval.md §4).
On schema failure, retry once with the validation error appended. If it fails again → abstain with
reason "drafting failed" (logged).

## 2. Verify (`verify.py`), per claim, pure functions + one batched NLI call

**Verifiable context** of a span = its evidence header (doc title, ref_no, clause path, page, validity dates) + span text.
Checks use the union of the verifiable contexts of the claim's cited spans.

| Check | Rule | Fail reason shown |
|---|---|---|
| (a) `spans_valid` | every span_id exists **and** was in the evidence pack | "cites evidence that wasn't retrieved" |
| (b) `numbers_ok` | every numeric token in the claim (money, percent, number with unit, date, range, and nil/no-charge words) appears in the context with equal normalised value, using the same `parse_value` as facts-and-subjects.md §3. Ignore clause references (`clause 7.2`, `cl. 8.1`, `para 1`) and list numbering. For `calc_input` claims, values present in the question are also accepted | "₹4 not found in cited text" |
| (c) `quote_ok` | text inside quotation marks in the claim (≥ 8 chars) has rapidfuzz `partial_ratio ≥ QUOTE_FUZZ_MIN` against the context | "quoted text doesn't match the source" |
| (d) `version_ok` | every cited span's clause status at as-of is `in_force` (amendments.md §4), except claims of kind `history` | "cites a superseded clause (replaced by …)" |
| (e) `hhem` | `/nli` score with premise = context (≤ 2,000 chars), hypothesis = claim text; pass if ≥ `HHEM_THRESHOLD` | "not entailed by the cited text (0.21)" |
| (f) conflicts | contradictions.md §5. Only for claims passing (a)–(e) | — |

Verdict: fails any of (a)–(e) → `unsupported`; passes (a)–(e) and (f) finds an in-force conflict → `contradicted`;
otherwise `supported`. Run checks (a)–(d) first and skip the NLI call for claims that already failed.

`passed` (for faithfulness) = verdict ∈ {supported, contradicted} (ADR-009).

## 3. Gate (`gate.py`)

```
supported   = [c for c in claims if verdict == supported]
contested   = [c for c in claims if verdict == contradicted]
blocked     = [c for c in claims if verdict == unsupported]
missing     = draft.missing + [f"No verified evidence for: {sq}" for sq in sub_questions with no supported/contested claim]

status = "abstained" if not supported and not contested
       = "conflict"  if contested
       = "partial"   if supported and (missing or blocked)
       = "answered"  otherwise
```

- `abstained` → body text: **"I don't have proof for this in the uploaded documents."** + `missing_evidence` list.
  Blocked claims are still listed (collapsed) so judges can see what was stopped.
- `conflict` → the body shows supported claims (if any), then "The documents disagree:" + one disagreement card per subject.
- `faithfulness_pct = round(100 * passed / drafted, 1)`; if drafted == 0 → show "—".

## 4. Assemble (`assemble.py`)

- `disagreements`: grouped by subject (contradictions.md §5.3).
- `chains`: for every evidence clause whose version key has > 1 version (amendments.md §5). Always included for intent `current_rule` / `history`.
- `calculation`: §5 below.
- Persist the user message + assistant message (answer_json) and append the full record to `logs/answers.jsonl`.
- Chat title: on the first message, the first 6 words of the question.

## 5. Calculator (`calc.py`), P1

| kind | Inputs | Formula | Notes |
|---|---|---|---|
| `emi` | P (INR), annual_rate_pct, n (months) | r = rate/12/100; EMI = P·r·(1+r)^n / ((1+r)^n − 1) | round to the nearest rupee; show r, (1+r)^n, EMI |
| `late_fee_total` | fee_per_instalment, count | fee × count | if late_payment_fee is contested at as-of → compute per side and show all; mention any cap |
| `prepayment_charge` | outstanding (INR), pct **or** nil flag | outstanding × pct/100, or 0 if nil applies | uses the in-force version at as-of; GST excluded unless a rate is cited |

Input sourcing: `plan.calc.given` (from the question, `source: "question"`) + `calc_input` claims from the draft (each
must pass verification (a)–(e)). A required input still missing → no calculation; add
"Missing input: annual interest rate" to `missing_evidence`. The LLM never sees or produces the result.

Reference values for tests: `emi(500000, 13.5, 36) == 16968` (±1); `prepayment_charge(200000, 3) == 6000`.

## 6. Hindi (`translate.py`), P2

- Detect: Devanagari characters `[ऀ-ॿ]` > 30% of letters → `language = "hi"` (or the chat setting forces it).
- Question → English via LLM (prompt `translate.md`, JSON `{"text": ...}`); store both.
- The whole pipeline runs in English. After the gate, translate `supported` claim texts, missing items and the status line to
  Hindi in one call (JSON list of the same length). **Number guard:** the digits in each translated claim must equal
  those in the English claim; otherwise show the English claim. Quotes are never translated.
- UI strings: a small dict `app/i18n.py` with `en` / `hi` labels.

## Tests (`tests/test_verify.py`)

- numbers_ok: "late fee is ₹500" vs span "₹500 per instalment" → True; vs "Rs. 500/-" → True; "₹5,000" → False; "4%" vs "3%" → False.
- "No prepayment charge applies" vs span "No prepayment charge shall be levied…" → True (nil handling).
- version_ok: a claim citing D1:7.2 at 2026-11-22 → False; the same claim as kind `history` → True.
- Gate status table: one test per status.
- Calc reference values above.

## Implementation notes (M4)

- Files: `draft.py` (+ `prompts/draft.md` v3), `verify.py`, `gate.py`, `assemble.py`, `core/normalize.py`; `AnswerJSON` is in `core/models.py`. `assemble.answer(conn, question, chat_id, as_of, client, retriever, on_stage, persist)` returns an `AnswerJSON`.
- Verify context = the span's evidence line without its `[id]` prefix (doc title, ref no, clause, page, effective date + text), so header numbers/dates are legitimate; the eval re-checks displayed claims independently with title/ref/effective date + raw span text.
- `verify_claims` calls `/nli` once for all claims that passed (a)-(d). If the service is down the claim stays unsupported ("could not be checked"), never displayed.
- `apply_threshold` re-decides saved claims at another HHEM threshold: `scripts/eval.py --hhem-sweep 0.3,0.5` re-gates the latest `eval_*.json` without model calls.
- Disagreements (M6), chains (M5) and calculation (M9) are empty in M4; their slots in `assemble.answer` are commented. Hindi (M10) not started.
- Lessons: prompt rules matter more than checks for off-topic answers (ADR-014); keep `missing` honest (rule 12) or every answer turns `partial`.
- Not done in M4: quote exactness gate from PDF bboxes (eval.md); the UI renders `Span.text` from the DB so quotes are stored text by construction; the bbox cross-check is scheduled with the evidence viewer (M7).
