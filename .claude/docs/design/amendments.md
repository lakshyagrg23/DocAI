# Design: Amendment chains and as-of resolution (ingest time + lookup at query time)

Covers FR-9, FR-18, FR-19 (Amendments page). Code: `core/ingest/amendments.py`, `core/retrieval/expand.py`, `core/versions.py`.
Data model borrows from Akoma Ntoso: each change is a dated, typed modification of a target provision, and the
point-in-time text = the latest modification in force on that date.

## 1. Detection

Clauses whose text matches

```python
AMEND_RX = r"\b(amend(?:ed|ment)?|substitut(?:e|ed|ion)|supersed(?:e|ed|es|ession)|replac(?:e|ed)|insert(?:ed)?|"
           r"delet(?:e|ed)|omit(?:ted)?|stand[s]? (?:modified|amended)|in partial modification|with effect from|w\.e\.f\.)\b"
```

(case-insensitive) or belonging to a doc with `doc_type == "amendment"` are sent with an `amendments` request in the
extraction call (facts-and-subjects.md §2). Output items are `AmendmentDirective` (data-model.md).

Prompt rules:
- `target_ref` = the target document exactly as named in the text.
- `target_path` = the clause number being changed ("7.2"), or null when the whole document is superseded.
- `new_text_span_ids` = the spans containing the replacement wording (for substitute/insert).
- `effective_date` = the stated date; null if none stated (code then uses the amending doc's effective_date).
- "In supersession of Amendment No. 1" → an extra directive `supersede_amendment` targeting that amendment document.

**Segmentation caveat:** in amendment docs, quoted replacement text such as `'7.2 A prepayment charge…'` must NOT start a
new clause. segment.py treats a line beginning with a quote mark (`'`, `‘`, `"`, `“`) or inside an open quote as a continuation.

## 2. Target resolution

1. Candidate docs: all docs except the source doc. Score = max rapidfuzz `partial_ratio` of `target_ref` against
   `ref_no`, each `ref_alias`, and `title`. Accept the best if ≥ 85; ties are broken by the most recent issue_date before the source's.
2. Target clause: `{target_doc_id}:{target_path}` must exist (for substitute/delete). For insert it may not exist yet.
3. Unresolved → keep the edge with `resolved=0`. The Amendments page shows a warning: "Amends X, which is not in the library".
   A later upload of X triggers re-resolution of unresolved edges (incremental, ADR-005).

## 3. Version timeline (`core/versions.py: rebuild(version_key)`)

```
base   = clause vk (if it exists) with valid_from = base doc effective_date
edges  = resolved edges targeting vk, sorted by (effective_date, source doc issue_date)
versions = [V0(base)]
for e in edges:
    prev = versions[-1]; prev.valid_to = e.effective_date
    substitute → append V(clause = e.source_clause, spans = e.new_text_span_ids, valid_from = e.effective_date)
    insert     → if no base: V0 = V(source, valid_from = eff) else treat as substitute
    delete     → append V(clause = None, deleted = True, valid_from = eff)
supersede_doc(target doc T, eff): for every vk whose current version's doc == T → close it at eff (deleted marker)
supersede_amendment(target amendment A, eff): close versions whose clause doc == A at eff, unless a later edge already did
write rows to clause_versions; set clauses.version_key = vk for every source clause in the chain
```

Rebuild runs for every vk touched by a new or changed edge, then the conflict scan runs for the subjects of facts in those clauses.

## 4. Status lookup (`core/versions.py`)

```python
def status(clause_id, as_of) -> Literal["in_force","superseded","future","deleted"]:
    rows = versions_for(clause.version_key)
    if not rows:                       # never amended
        d = doc.effective_date
        return "in_force" if d <= as_of and not doc_superseded(doc, as_of) else "future"
    v  = version_containing(rows, as_of)  # valid_from <= as_of < valid_to (None = ∞)
    me = version_of(rows, clause_id)      # the row whose clause_id == clause_id
    if v is None:                         # as_of is before the first version
        return "future"
    if v.clause_id == clause_id:
        return "in_force"
    if me.valid_from > as_of:
        return "future"
    return "superseded"                   # includes the case where v is a deleted marker

def key_status(version_key, as_of) -> Literal["active","deleted","not_yet"]  # used to say "this rule was deleted on …"
```

A clause appears in at most one version of its key.

## 5. Chain output (query time)

For each in-force evidence clause whose key has more than one version, build a chain (data-model.md `chains[]`):
the steps in order, each with doc title, clause_id, action (`original | substituted | inserted | deleted`), valid_from,
valid_to, a quote span (for substitute: the first `new_text_span_id`; for the original: the clause's first span),
and `in_force_step`. The UI renders a vertical timeline.

**Version check in verification** (answering.md §Verify d): a claim citing any span whose clause status ≠ `in_force`
fails `version_ok`, unless the claim's kind is `history` (it then must name the period).

## 6. Amendments page data

- Per document: the edges it issued (source) and received (target), with effective dates.
- Per version key with > 1 version: the timeline plus a "View clause as of [date]" control that shows the in-force text.

## Tests (`tests/test_versions.py`)

- After D1 + D3 + D4: versions of `D1:7.2` = 3; valid ranges [2024-01-15, 2025-04-01), [2025-04-01, 2026-01-01), [2026-01-01, ∞).
- `status("D1:7.2", "2026-11-22") == "superseded"`; the D3 version status at 2025-06-01 == "in_force"; the D4 version at today == "in_force".
- Ingest order independence: ingesting D4 before D3 yields the same timeline.
- An edge to a non-existent doc is stored with resolved=0, and resolves after that doc is ingested.

## Implementation notes (M5)

- Files: `core/ingest/extract.py` (facts), `core/subjects.py` + `core/subjects_seed.py`, `core/ingest/amendments.py` (directives + resolution), `core/versions.py` (rebuild, status, chains), prompts `extract_facts.md` v1, `extract_amendments.md` v2, `same_subject.md` v1. Both stages run as `pipeline.POST_STAGES`.
- **Facts and directives use two LLM calls**, not one (§1 said "same call"): a 4B model does better with one task per prompt. Directives are only requested for clauses of `amendment` docs or matching `AMEND_RX`.
- **`AMEND_RX` fixed**: the spec's `supersed(?:...|ession)` never matched "supersession"; it is now `supersession|supersed(?:e|ed|es)`.
- **Validation of directives (code side):** the evidence span must exist in the document; for substitute/insert/delete `target_path` must literally appear in the evidence text (if the model left it empty it is recovered from "Clause N" when exactly one such reference exists: the 4B model often omits it); supersede_* need supersession wording. Missing `new_text_span_ids` fall back to the rest of the evidence clause.
- **Target resolution adds a guard to §2:** for substitute/delete a candidate document must contain the target clause (`D1:7.2` exists, `D3:7.2` does not), because an amendment's title repeats the agreement's reference number. Ties go to the longer matched name (so `KF/PLA/2024/AMD-1` beats `KF/PLA/2024`). `resolve_all` re-resolves every edge on each ingest, so a late upload or re-ingest heals earlier edges.
- **Rebuild is global** (`versions.rebuild_all`) instead of per touched key: the corpus is small, and it makes ingest order irrelevant (tested for 3 orders). Deleting a document's content also deletes the edges it sourced.
- `supersede_doc` gives every clause of the superseded document a timeline (original + deletion marker, `clause_id` NULL); `expand` skips marker rows; `key_status` reports `deleted`.
- Chains are built from the cited clauses (plus all evidence clauses for `current_rule` / `history` intents) and are omitted when the answer abstains. Step dict: `clause_id, doc_id, doc_title, ref_no, valid_from, valid_to, action, span_id, text`; `in_force_step` is -1 when no version covers the as-of date.
- Subject canonicalisation: seed → fuzzy (`token_set_ratio >= 90`, but a one-word alias such as "interest" or "age" must equal the whole label) → embedding + LLM `same_subject` → new subject. Embeddings of subject labels are computed on demand (few subjects), so there is no `subjects.npy`.
