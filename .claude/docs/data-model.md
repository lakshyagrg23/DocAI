# Data model

The corpus is stored at three levels:

- **Clause**: identity and versions. "What is the rule, and which version applies?"
- **Span**: citation. "Which exact words, where on which page?"
- **Fact**: comparison. "Can code compare this with another source?"

Chunking by clause only is not enough. Circulars, FAQs and fee tables often have no numbering, and one clause can
hold several rules. Comparing whole clauses is fuzzy and needs O(n²) LLM calls. Comparing facts grouped by subject
is exact for numbers and dates.

## ID conventions

| Entity | ID format | Example |
|---|---|---|
| Document | short slug, assigned at register (demo: `D1`…`D6`; uploads: `U` + 6 hex chars of sha256) | `D1` |
| Clause | `{doc_id}:{path}` | `D1:7.2`, `D2:table1.row2`, `D6:p1.q1` |
| Span | `{clause_id}#s{n}` | `D1:7.2#s1` |
| Fact | `f_{ulid}` | |
| Subject | snake_case key | `late_payment_fee` |
| Version key | `{target_doc_id}:{path}` | `D1:7.2` (shared by D1:7.2, D3:1, D4:1 versions) |
| Edge, conflict, chat, message | `e_`, `c_`, `chat_`, `m_` + ulid | |

Paths: numbered clauses use their numbering (`7.2`, `7.2(b)`, `8.1(iii)`). Unnumbered paragraphs use `p{page}.{n}`.
Table rows use `table{t}.row{r}` (the header row is `row0`, which is stored but never cited alone). FAQ Q&A pairs use `p{page}.q{n}`.

## SQLite schema (`core/db.py`)

```sql
CREATE TABLE documents(
  doc_id TEXT PRIMARY KEY, title TEXT, doc_type TEXT,        -- agreement|schedule|amendment|circular|faq|policy|other
  issuer TEXT, ref_no TEXT, ref_aliases TEXT,                -- JSON list
  issue_date TEXT, effective_date TEXT,                      -- ISO yyyy-mm-dd
  sha256 TEXT UNIQUE, filename TEXT, pages INT, has_ocr INT DEFAULT 0, language TEXT DEFAULT 'en',
  status TEXT, status_detail TEXT, created_at TEXT);
CREATE TABLE pages(doc_id TEXT, page_no INT, width REAL, height REAL, is_ocr INT, ocr_conf REAL,
  PRIMARY KEY(doc_id, page_no));
CREATE TABLE clauses(
  clause_id TEXT PRIMARY KEY, doc_id TEXT, path TEXT, heading_trail TEXT, kind TEXT,
  text TEXT, page_start INT, page_end INT, parent_id TEXT,
  version_key TEXT,           -- own id by default; for amendment-content clauses = target key (set by amendments.py)
  ord INT);                   -- reading order in the document
CREATE TABLE spans(
  span_id TEXT PRIMARY KEY, clause_id TEXT, doc_id TEXT, page INT,
  text TEXT, bboxes TEXT,     -- JSON [[x0,y0,x1,y1],...] in PDF points, origin top-left (PyMuPDF convention)
  char_start INT, char_end INT, is_table_row INT DEFAULT 0, ocr_conf REAL);
CREATE TABLE windows(         -- retrieval units
  window_id TEXT PRIMARY KEY, clause_id TEXT, doc_id TEXT, text TEXT, span_ids TEXT, row_idx INT); -- row_idx into dense.npy
CREATE TABLE subjects(subject_id TEXT PRIMARY KEY, label TEXT, aliases TEXT, emb_row INT);
CREATE TABLE facts(
  fact_id TEXT PRIMARY KEY, clause_id TEXT, span_id TEXT, subject_id TEXT,
  attribute TEXT, op TEXT,    -- eq|max|min|range|bool
  value_type TEXT,            -- money|percent|number|duration|date|bool|enum|text
  value_norm TEXT,            -- JSON, see FactValue
  value_raw TEXT, scope TEXT, -- JSON dict e.g. {"rate_type":"floating","borrower":"individual"}
  modality TEXT, condition_text TEXT);
CREATE TABLE amendment_edges(
  edge_id TEXT PRIMARY KEY, source_clause_id TEXT, target_doc_id TEXT, target_path TEXT,
  action TEXT,                -- substitute|insert|delete|supersede_doc|supersede_amendment
  new_text_span_ids TEXT, effective_date TEXT, evidence_span_ids TEXT,
  confidence REAL, resolved INT, raw_target_ref TEXT);
CREATE TABLE clause_versions(
  version_key TEXT, version_no INT, clause_id TEXT,  -- clause whose text IS this version
  valid_from TEXT, valid_to TEXT,                    -- valid_to NULL = open-ended
  edge_id TEXT, PRIMARY KEY(version_key, version_no));
CREATE TABLE conflicts(
  conflict_id TEXT PRIMARY KEY, subject_id TEXT, fact_a TEXT, fact_b TEXT,
  type TEXT,                  -- numeric|date|rule|eligibility|text
  overlap_from TEXT, overlap_to TEXT, detected_by TEXT, explanation TEXT, severity TEXT,
  differing TEXT,             -- JSON {"a":[values],"b":[values]}: only the disputed values (contradictions.md §2)
  UNIQUE(fact_a, fact_b));
CREATE TABLE chats(chat_id TEXT PRIMARY KEY, title TEXT, created_at TEXT, as_of_date TEXT,
  language TEXT DEFAULT 'auto', doc_scope TEXT);    -- doc_scope JSON list or NULL = all
CREATE TABLE messages(msg_id TEXT PRIMARY KEY, chat_id TEXT, role TEXT, content TEXT,
  answer_json TEXT, created_at TEXT);
CREATE TABLE ingest_jobs(job_id TEXT PRIMARY KEY, doc_id TEXT, path TEXT, state TEXT, error TEXT,
  created_at TEXT, updated_at TEXT);
```

Indexes: `spans(clause_id)`, `clauses(doc_id)`, `clauses(version_key)`, `facts(subject_id)`, `facts(clause_id)`,
`amendment_edges(target_doc_id,target_path)`, `messages(chat_id)`.

Files in `DATA_DIR`: `corpus.db`, `index/dense.npy`, `index/bm25.pkl`, `subjects.npy`, `pages/{doc_id}/{page}.png`
(cache), `uploads/`, `logs/answers.jsonl`, `logs/ingest.log`.

## Pydantic models (`core/models.py`)

```python
class FactValue(BaseModel):
    amount: float | None = None      # money/number/percent value; for range = None
    unit: str | None = None          # INR | % | months | years | days
    low: float | None = None         # range
    high: float | None = None
    date: str | None = None          # ISO
    flag: bool | None = None         # bool
    text: str | None = None          # enum/text

class ExtractedFact(BaseModel):      # LLM output item (facts-and-subjects.md)
    subject: str; attribute: str
    op: Literal["eq","max","min","range","bool"]
    value_type: Literal["money","percent","number","duration","date","bool","enum","text"]
    value_raw: str                   # must appear in span text (verified)
    span_id: str
    scope: dict[str, str] = {}
    modality: Literal["must","may","must_not","info"] = "info"
    condition_text: str | None = None

class AmendmentDirective(BaseModel): # LLM output item (amendments.md)
    action: Literal["substitute","insert","delete","supersede_doc","supersede_amendment"]
    target_ref: str                  # as written: "Personal Loan Agreement KF/PLA/2024"
    target_path: str | None          # "7.2"; None for whole-document actions
    effective_date: str | None
    new_text_span_ids: list[str] = []
    evidence_span_ids: list[str]

class DraftClaim(BaseModel):
    text: str; span_ids: list[str]
    kind: Literal["fact","history","calc_input"] = "fact"

class Draft(BaseModel):
    claims: list[DraftClaim]
    missing: list[str] = []          # evidence the model looked for but did not find

class ClaimCheck(BaseModel):
    spans_valid: bool; numbers_ok: bool; quote_ok: bool; version_ok: bool
    hhem: float | None; conflict_ids: list[str] = []

class VerifiedClaim(BaseModel):
    text: str; span_ids: list[str]
    verdict: Literal["supported","unsupported","contradicted"]
    checks: ClaimCheck; reason: str | None = None
```

## Answer JSON (stored in `messages.answer_json`, rendered by the UI)

```json
{
  "status": "answered | partial | conflict | abstained",
  "question": "...", "question_en": "...", "language": "en|hi", "as_of_date": "2026-11-22",
  "intent": "lookup|multi|current_rule|history|calculation",
  "claims": [VerifiedClaim, ...],                 // verdict == supported only
  "blocked_claims": [VerifiedClaim, ...],         // unsupported, with reason
  "disagreements": [{"conflict_id": "...", "subject": "late_payment_fee",
                     "sides": [{"span_id":"D1:8.1#s1","doc":"D1","page":4,"status":"in_force"},
                               {"span_id":"D2:table1.row2","doc":"D2","page":1,"status":"in_force"}],
                     "explanation": "₹500 vs ₹750 per instalment"}],
  "missing_evidence": ["GST rate applicable to the processing fee"],
  "chains": [{"version_key":"D1:7.2","steps":[{"clause_id":"D1:7.2","valid_from":"2024-01-15","valid_to":"2025-04-01","action":"original","span_id":"D1:7.2#s1"}, ...],"in_force_step":2}],
  "calculation": {"kind":"emi","formula":"P·r·(1+r)^n/((1+r)^n−1)",
                  "inputs":[{"name":"P","value":500000,"source":"question"},
                            {"name":"annual_rate_pct","value":13.5,"span_id":"D1:5.1#s1"},
                            {"name":"n","value":36,"source":"question"}],
                  "steps":["r = 13.5/12/100 = 0.01125", "..."], "result":16968.0, "unit":"INR"},
  "faithfulness_pct": 83.3, "drafted": 6, "passed": 5,
  "prompt_versions": {"plan":"v1","draft":"v1"}, "timings_ms": {"retrieve":900,"draft":7000,"verify":1500}
}
```

Status rules are in design/answering.md §Gate.

> **Workspaces (ADR-024):** `documents` and `chats` also carry `workspace_id`, `sha256` is unique per workspace, and a new `workspaces(workspace_id, name, created_at)` table exists. See design/workspaces.md.
