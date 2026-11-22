# Product spec (condensed PRD)

Source PRD: "PRD — Verifiable Document AI (24-hour prototype)" (claude.ai doc). This file is the coding-time copy.
Where this file and the PRD differ, this file plus `decisions.md` win.

## Goal

A deployed web app for high-stakes PDFs (loan agreements, schedules of charges, amendments, regulatory circulars,
policy FAQs). It:

- answers questions across several PDFs, including tables and clauses that run across pages;
- backs every claim with doc name + page + **verbatim quote**;
- flags **contradictions** (numbers, dates, rules, eligibility) side by side;
- resolves **amendment chains** (C amends B amends A) to the rule in force on a date and shows the chain;
- **verifies every claim** before showing it, and abstains with "I don't have proof" + the missing evidence;
- shows a **faithfulness score** per answer;
- runs only on open-source models (no paid AI API).

## Scope

| Priority | Features |
|---|---|
| **P0** | Multi-PDF upload + ingest (digital, tables) · hybrid retrieval · claim-based answers with exact citations · verification + abstention · faithfulness % · contradiction detection (side by side) · amendment chains + rule in force today · **multiple chats** · document library with ingest status · deployed public URL · README with pipeline diagram + model list |
| **P1** | Scanned PDFs via OCR · page highlight of cited span · calculator (EMI, late fee total, prepayment charge) with working · as-of date picker · Conflicts page + Amendments page |
| **P2** | Hindi Q&A · per-chat document scope · export answer as audit JSON/Markdown |
| **Out** | Auth · handwriting OCR · DOCX/XLSX input · editing documents |

Build order is strictly P0 → P1 → P2. P0 must pass its eval gates before P1 work starts.

## Functional requirements and acceptance criteria

| ID | Pri | Requirement | Acceptance |
|---|---|---|---|
| FR-1 | P0 | Upload several PDFs; parse text, tables and word positions | 3-doc upload reaches Ready; every span has page + bbox |
| FR-2 | P0 | Clause segmentation with numbering paths; tables kept as table-row spans; clauses running across pages merged | D1 clause 7.2 (spans p.3→4) is one clause; each D2 table row is one span |
| FR-3 | P0 | Hybrid retrieval (bge-m3 dense + BM25, RRF) + reranker; evidence combined across docs | Multi-doc questions retrieve all expected clauses in top-8 |
| FR-4 | P0 | LLM drafts an answer as claims, each citing span_ids from the given evidence | Output validates against schema; unknown span_ids are rejected |
| FR-5 | P0 | Each displayed claim shows doc title, page and verbatim quote rendered from the stored span | Quote == source text (exact) |
| FR-6 | P0 | Verify each claim: span validity, number/date match, version status, NLI (HHEM) ≥ τ → supported / unsupported / contradicted | Planted wrong number → unsupported |
| FR-7 | P0 | Only supported claims in the body; blocked claims listed with reasons; zero supported → abstain + missing list | All 6 unanswerable test questions abstain (gate ≥ 5/6) |
| FR-8 | P0 | Conflicts between facts in force at the same time are detected at ingest; surfaced in answers and on the Conflicts page | 3/3 planted conflicts flagged with both quotes |
| FR-9 | P0 | Amendment edges extracted at ingest; version timeline per clause; answer from the in-force version with the chain shown | "Prepayment charge today (floating)?" → Nil from D4 with chain D1→D3→D4 |
| FR-10 | P0 | Faithfulness % = claims passing checks (a)–(c) ÷ claims drafted × 100, shown on every answer | Number matches the per-claim labels |
| FR-11 | P1 | Click a citation → page image with the span highlighted | Highlight covers the quoted words |
| FR-12 | P2 | Hindi question → Hindi answer; quotes stay in the source language | Hindi test passes |
| FR-13 | P1 | Calculation questions: inputs from cited spans or the question, maths in Python, working shown | EMI(5,00,000; 13.5%; 36) = ₹16,968 ± 1 |
| FR-14 | P0 | Public deployed app + README (pipeline diagram, models) | URL reachable; README complete |
| FR-15 | P0 | **Multiple chats:** create / rename / delete / switch; each keeps history, as-of date, language | Two chats keep separate histories after page reload |
| FR-16 | P1 | Scanned PDFs: image-only pages detected and OCR'd; OCR spans flagged with confidence | D6 questions answered with an OCR badge |
| FR-17 | P0 | Document library: title, type, ref no, dates, pages, clauses, OCR flag, status (Queued / Parsing / OCR / Extracting / Ready / Failed) | Status updates live during upload |
| FR-18 | P1 | Per-chat as-of date (default today) drives version resolution | As-of 2025-06-01 → prepayment 3% (D3) |
| FR-19 | P1 | Conflicts page (grouped by subject) + Amendments page (chains per clause) | Lists all planted items |

## Non-functional requirements

| Area | Requirement |
|---|---|
| Privacy | Document text goes only to our model service (bearer token). No document text in logs except `answers.jsonl` in DATA_DIR. |
| Determinism | temperature 0; seeds fixed; prompt files versioned (`v1`, `v2`…) and the version stored with each answer |
| Latency | Warm answer p50 ≤ 20 s, p95 ≤ 40 s; ingest of a 10-page digital PDF ≤ 2 min; OCR ≈ 3–5 s/page |
| Cost | ≤ $15 Modal credit for build + judging |
| Degradation | Model service down/cold → amber status + "warming up" message; library/conflicts/amendments pages still work |
| Auditability | Answer JSON downloadable; includes span_ids, check results, scores, prompt version, as-of date |

## Glossary

- **Clause**: the identity + version unit (`{doc_id}:{path}`, e.g. `D1:7.2`).
- **Span**: the citation unit (a sentence or one table row) with exact text, page, bboxes.
- **Fact**: normalised comparable assertion extracted from a span (subject, attribute, op, value, scope, validity).
- **Version key**: `(target_doc_id, path)`. All versions of one rule share it, across amendment documents.
- **In force (as of d)**: the version whose `[valid_from, valid_to)` contains d.
- **Abstain**: answer status when no claim is supported; shows "I don't have proof" + the missing evidence.
