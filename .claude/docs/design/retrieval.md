# Design: Retrieval (plan → hybrid search → rerank → version expansion → evidence pack)

Covers FR-3, FR-18. Code: `core/answer/plan.py`, `core/retrieval/{bm25,hybrid,expand}.py`.

## 1. Query plan (`plan.py`, prompt `plan.md`)

Input: question (English, after translation if Hindi), chat as-of date. Output (guided JSON):

```json
{"intent": "lookup|multi|current_rule|history|calculation",
 "sub_questions": ["..."],                     // 1–3; the original question if simple
 "as_of_override": "2025-06-01" | null,       // a date the question itself states ("as of June 2025", "in 2024")
 "calc": {"kind": "emi|late_fee_total|prepayment_charge|none",
          "given": {"principal": 500000, "months": 36}}   // numbers the user supplied in the question
}
```

Rules in the prompt: "current", "today", "now" → `current_rule`; an explicit past date → `history` + `as_of_override`.
Effective as-of = `as_of_override or chat.as_of_date or today`.

## 2. Hybrid search (`hybrid.py`)

Per sub-question:
1. Dense: embed the query (`/embed`), dot product against `dense.npy` (normalised) → top `TOPK_DENSE` windows.
2. BM25: top `TOPK_BM25` windows.
3. Reciprocal rank fusion: `score(w) = Σ 1/(RRF_K + rank_i(w))` over both lists → top 30.
4. Rerank: `/rerank` with `(sub_question, window.text)` → keep top `RERANK_KEEP` windows.
5. Apply `chat.doc_scope` as a filter before step 3 when set (P2).

Merge across sub-questions: union of windows, keeping each window's best rerank score.

## 3. Version expansion (`expand.py`)

For every clause behind the kept windows:
- `vk = clause.version_key` → load all `clause_versions` rows for `vk` → add every version's clause to the candidate set,
  tagging each one with its status as of the as-of date: `in_force | superseded | future`.
  (See amendments.md for status computation. A clause with no versions row is in force if its doc
  `effective_date ≤ as_of` and the doc is not superseded; otherwise `future`.)
- Expanded versions are used for **chains** and **version checks**. Only `in_force` clauses go into the drafting evidence.
- Intent `history`: in-force is computed at `as_of_override`, so a past version becomes "in force" for that date.

## 4. Evidence pack

- Take spans of in-force candidate clauses, ordered by (best window rerank score desc, clause ord, span order).
- Cap at `EVIDENCE_MAX_SPANS` spans / `EVIDENCE_MAX_TOKENS` tokens. Always include whole clauses (all spans of a clause) when possible.
- Each span is presented to the LLM as:
  `[D1:7.2#s1] (Personal Loan Agreement KF/PLA/2024, cl. 7.2, p.3, in force from 2026-01-01 per Amendment No. 2) <text>`
  Including the doc title and validity lets the model phrase claims correctly without seeing superseded text.
- Also keep `context_spans` (superseded/future versions) for the chain builder; these are never shown to the drafting LLM.

## 5. Retrieval eval

`scripts/eval.py --retrieval-only` runs plan + search for every qa.yaml item that has `must_cite`, and reports
recall@8 (the expected clause_ids present among the kept windows' clauses). Gate: ≥ 90%.

Tuning order if recall is low: (1) check segmentation (is the clause text complete?), (2) add the heading trail to windows,
(3) raise RERANK_KEEP to 10, (4) add query expansion with the subject aliases from the `subjects` table
(e.g. "late fee" → "penal charge").

## Implementation notes (M3)

Deviations and details beyond the sections above (no behavioural conflict with the spec):
- **Original question is also searched.** `answer/plan.py:search_queries` = sub-questions + the question as asked. A sub-question split can drop half of a comparison
  (q27 lost the schedule-of-charges side). Cost: one extra search per question; results are unioned, best score per window.
- **Rerank is chunked** (`RERANK_CHUNK=10` passages per `/rerank` request) so a CPU model service stays under `AUX_TIMEOUT_S`; scores are identical.
- **`expand.py` already does the real status logic**, not the "all in force" stub: uses `clause_versions` rows when present, otherwise the doc `effective_date`
  (`[valid_from, valid_to)`, `valid_to` exclusive). M5 only has to populate edges/versions and `supersede_doc`.
  Spans of non-in-force clauses go to `EvidencePack.context_spans`, never to the drafting evidence.
- **Evidence line**: `[span_id] (Title Ref, <where>, p.N, effective YYYY-MM-DD) text`; `<where>` = `cl. 7.2` | `table 1 row 2` | `para p1.3`.
  The "in force from ... per Amendment" wording in §4 arrives with M5 (needs edges).
- **Plan cache** (eval only): `DATA_DIR/cache/plans.json`, keyed by `LLM_MODEL|question`; `--no-cache` bypasses. Planner calls dominate eval time on a CPU box.
- **Gate metric**: clause-level recall@8 over all `must_cite` clauses (item-level recall is printed too). `D6:p1.q1` (scanned) cannot be found until M9 OCR, so it stays a known miss.
- Index reload: `Retriever` compares the index files' mtimes and reloads after a re-ingest.
