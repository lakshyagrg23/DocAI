# Design: Contradiction detection

Covers FR-8, FR-19 (Conflicts page). Code: `core/ingest/conflicts.py`, `core/conflict_rules.py` (pure functions),
`core/answer/verify.py` (query-time lookup and re-check).

Principle: an **amendment is not a contradiction**. Two facts conflict only when their clauses are both in force at some
common time **and** are not versions of the same rule (they have different `version_key`s).

## 1. Candidate pairs (ingest time, per affected subject)

For subject S, take all facts with `subject_id = S`. Pre-merge: if one span or clause yields both a `min` and a `max` fact
for the same attribute, merge them into one `range` fact (e.g. age ≥ 21 and ≤ 58 → range 21–58).

A pair (a, b) is a candidate iff:
- `a.clause_id != b.clause_id` and `clause(a).version_key != clause(b).version_key`
- **scope compatible**: for every key present in both scopes the values are equal (a key present in only one scope is OK:
  general vs specific still conflicts, e.g. a regulator's cap applies to all products)
- `per` units are compatible (`per instalment` vs `per instance` are treated as equal; `per month` vs `per instalment` are not)
- **validity overlap**: `interval(a) ∩ interval(b) ≠ ∅`, where interval(x) = the clause's version interval
  (`clause_versions`), or `[doc.effective_date, doc superseded date or ∞)` if unversioned.

## 2. Comparison rules (`core/conflict_rules.py: compare(a, b) -> ConflictVerdict | None`)

| a.op \ b.op | Conflict when | Type |
|---|---|---|
| eq · eq | values differ (money: exact; percent: > 1e-6; duration: same unit and different) | numeric |
| eq · max | eq.amount > max.amount | rule |
| eq · min | eq.amount < min.amount | rule |
| range · range | low or high differ | eligibility if subject in {borrower_age, …} else numeric |
| range · eq | eq outside range | eligibility/numeric |
| bool(False = nil / not permitted) · eq(amount > 0) | always | rule |
| bool · bool | flags differ | rule |
| date · date (same attribute) | dates differ | date |
| max · max, min · min | **not** a conflict (the stricter one applies); store nothing | — |
| text / enum | send to the LLM judge (§3) | text |

`explanation` is a code template, e.g. `"₹500 per instalment (Personal Loan Agreement, cl. 8.1) vs ₹750 per instalment (Schedule of Charges, row 2)"`,
`"₹750 exceeds the ₹600 cap (FCB Circular FCB/2025/17, para 1)"`.
Severity: `high` for money, rate and eligibility; `medium` otherwise.
`differing` = the values that disagree on each side, e.g. C1 `{"a":[500],"b":[750]}`, C3 `{"a":[58],"b":[60]}` (only the high
bound differs), C2 `{"a":[750],"b":[600]}`, nil vs amount `{"a":["nil"],"b":[4]}`. Used at query time (§5) so that a claim
about an undisputed part of a fact (minimum age 21) is not marked contradicted.
`overlap_from` / `overlap_to` = the validity intersection.

## 3. LLM judge (text/enum only; prompt `judge_conflict.md`)

Input: subject, both spans with doc titles. Output `{"conflict": bool, "type": "rule|eligibility|text", "explanation": str}`.
Temperature 0. Store only if `conflict == true`. Never use the judge for numeric pairs: code decides those.

## 4. Incremental scan

When ingest adds facts or rebuilds versions, re-scan only the subjects of new facts and the subjects of facts in clauses
whose version intervals changed. Delete existing conflicts involving changed facts first (`UNIQUE(fact_a, fact_b)`,
with fact_a < fact_b lexicographically).

## 5. Query time (`verify.py`)

1. **Lookup:** for each claim that passed checks (a)–(c), collect facts on its cited spans. For each stored conflict
   involving one of those facts where `as_of ∈ [overlap_from, overlap_to)` and the *other* fact's clause is `in_force`
   at as_of → mark the claim `contradicted` and attach the conflict_id, **but only if the claim asserts the disputed part**:
   the claim's normalised value tokens intersect `conflict.differing[side]`, or (for bool/text conflicts) the claim restates
   the fact. Example: C3 differs only on the upper age bound (58 vs 60), so "The minimum age is 21 [D1:3.1]" is **not**
   contradicted (q28), while "Applicants must be aged 21 to 58 [D1:3.1]" is.
2. **Re-check:** run `compare()` pairwise on facts of in-force evidence clauses that share a subject (usually < 20 pairs).
   New conflicts found → persist with `detected_by="query"` and treat as in step 1.
3. Group disagreements by subject: one card per subject listing every side (doc, page, quote, status), e.g.
   late_payment_fee: D1 ₹500 · D2 ₹750 · D5 cap ₹600 (in force from 2025-11-01).

## 6. Expected conflicts in the demo corpus (ground truth)

| # | Subject | Sides | Type | Overlap |
|---|---|---|---|---|
| C1 | late_payment_fee | D1 cl. 8.1 ₹500 (eq) vs D2 row "Late payment fee" ₹750 (eq) | numeric | 2024-01-15 → ∞ |
| C2 | late_payment_fee | D2 ₹750 (eq) vs D5 para 1 cap ₹600 (max) | rule | 2025-11-01 → ∞ |
| C3 | borrower_age | D1 cl. 3.1 range 21–58 vs D6 FAQ range 21–60 | eligibility | 2025-06-01 → ∞ |

Must **not** be flagged: D1 7.2 (4%) vs D3 (3%) vs D4 (nil/2%), since they are versions of the same key;
D1 ₹500 vs D5 cap ₹600 (500 ≤ 600).

## Tests (`tests/test_conflicts.py`)

- Unit tests for every row of the comparison table.
- After ingesting the corpus: exactly C1, C2, C3 exist (subjects and fact pairs match); no conflict involves two versions of `D1:7.2`.

## Implementation notes (M6)

- Files: `core/conflict_rules.py` (pure: `FactView`, `compare`, `candidate`, `merge_ranges`, `overlap`, `scopes_compatible`), `core/ingest/conflicts.py` (scan + store, stage "Checking conflicts"), `core/answer/disagree.py` (query time), prompt `judge_conflict.md` v1 (text/enum pairs only).
- **The ingest scan re-scans every subject** after each document instead of only the new subjects: a new document can change the version intervals of old facts, the corpus is small, and conflict ids are deterministic (`C_<sha1(fact_a|fact_b)[:8]>`), so re-scans are idempotent.
- `compare` keeps sides attached to the facts as passed in (a `max` vs `eq` pair is normalised internally and swapped back), so `differing["a"]` always belongs to `fact_a`. A merged range fact carries the `min` fact's id; lookups by span find it through that id.
- **Query time lives in `disagree.py`, not in `verify.py`** (verify stays free of DB access): `mark_contradicted` runs after verify and turns a supported claim into `contradicted` only when it states a value in `differing[side]` (C3: "minimum age is 21" is not contradicted, "21 to 58" is). A conflict only applies when `as_of` is inside its overlap and both clauses are in force then.
- **Addition to the spec (partner expansion):** `add_partners` appends the spans of the clause on the other side of any conflict in effect to the evidence pack, so the answer shows both sides even when retrieval only found one (q27: retrieval misses `D2:table1.row2`, the circular's side pulls it in). Also `recheck` persists conflicts that the ingest scan missed (`detected_by='query'`).
- Disagreement cards are built only from conflicts that contradicted a displayed claim, grouped by subject: `{conflict_id, conflict_ids, subject, type, severity, explanation, sides[{span_id, clause_id, doc, doc_title, page, status, value, text, ocr}]}`.
- C3 (borrower age) needs the scanned FAQ, so it is verified with synthetic facts in `tests/test_conflicts.py` until M9 (OCR); live C1 and C2 are stored exactly.
