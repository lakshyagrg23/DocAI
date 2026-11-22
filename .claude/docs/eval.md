# Evaluation (`scripts/eval.py`)

Runs `tests/qa.yaml` against the ingested corpus through the same `assemble.answer()` the UI uses (with a throwaway
chat per item and `as_of` set from the item). Prints a per-item table and the release gates, and writes
`DATA_DIR/logs/eval_{timestamp}.json`.

Flags: `--only q09,q25` · `--type conflict` · `--retrieval-only` (recall@8 only, no drafting) · `--skip-types scanned,hindi`
(until milestones M9 / M10) · `--hhem-sweep 0.3,0.4,0.5,0.6` (re-runs only the verification step on cached drafts to pick
`HHEM_THRESHOLD`; record the chosen value in decisions.md).

## Per-item scoring

| Field | Pass rule |
|---|---|
| `status` | `answer.status == expect.status` |
| `must_cite` | every listed clause_id is the clause of ≥ 1 span cited by a displayed claim, a disagreement side, a chain step marked in force, or a calc input |
| `forbid_cite` | none of these clause_ids appear in displayed claims or disagreement sides |
| `values` | each expected value (normalised with `parse_value`; `"nil"` matches flag False or amount 0) appears in displayed claim texts, disagreement quotes or the calc result |
| `forbid_values_in_body` | not present in displayed (supported) claim texts |
| `conflict_subjects` | each subject appears in `disagreements`; `[]` means no disagreements at all |
| `chain` | `chains` contains a chain whose step clause_ids equal the list, in order |
| `calc_result` | `abs(calculation.result − expected) ≤ calc_tolerance` |
| `ocr_badge` | ≥ 1 cited span has `ocr_conf` not null |
| `language` | `answer.language == expected` |

Item passes when all present fields pass.

## Global metrics and release gates (P0 gates must pass before deploying)

| Metric | Definition | Gate |
|---|---|---|
| Unsupported claims displayed | displayed claims whose verdict ≠ supported, re-checked independently by eval (re-run checks a–d) | **0** (P0) |
| Quote exactness | displayed citation span text == source text from PyMuPDF at the span's bboxes (table rows: every cell text found in the row) | **100%** (P0) |
| Abstention recall | unanswerable items with status abstained ÷ 6 | **≥ 5/6** (P0) |
| False abstention | answerable items wrongly abstained ÷ answerable items | ≤ 10% (P0) |
| Conflict recall | items of type conflict / multi with `conflict_subjects` passing | **3/3 corpus conflicts surfaced** (P0) |
| Conflict precision | the negative control (q28) and q05 show no disagreements | pass (P0) |
| Version correctness | current_rule + as_of items passing | **8/8** (P0) |
| Retrieval recall@8 | from `--retrieval-only` | **≥ 90%** (P0) |
| Calc | calc items passing | 3/3 (P1) |
| Scanned | scanned items passing | 2/2 (P1) |
| Hindi | q40 | pass (P2) |
| Latency | p50 / p95 of warm end-to-end answer time | ≤ 20 s / ≤ 40 s |
| Faithfulness (avg) | mean `faithfulness_pct` over answered items | report only (no gate) |

## Debugging guide (where to look when an item fails)

| Symptom | Check first |
|---|---|
| Wrong clause cited / missing | `--retrieval-only` for that item → segmentation of the clause → window text |
| Correct claim blocked | the blocked claim's checks in the answer JSON: numbers_ok (normaliser), version_ok (timeline), hhem score |
| Abstained but should answer | the draft's `missing`; evidence pack contents (logged); HHEM threshold |
| Answers an unanswerable question | the displayed claim probably answers a *different* question; tighten draft prompt rule 6 and add "claims must directly answer the question" |
| Conflict missing | facts for both clauses (subject ids equal?), scope compatibility, validity overlap |
| Spurious conflict | the two facts' scopes (`rate_type`, `per`), version_key equality |
