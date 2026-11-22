"""Pydantic models (data-model.md). LLM I/O and DB rows."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class FactValue(BaseModel):
    amount: float | None = None  # money/number/percent value; for range = None
    unit: str | None = None  # INR | % | months | years | days
    low: float | None = None
    high: float | None = None
    date: str | None = None  # ISO
    flag: bool | None = None
    text: str | None = None


class ExtractedFact(BaseModel):
    subject: str
    attribute: str
    op: Literal["eq", "max", "min", "range", "bool"]
    value_type: Literal["money", "percent", "number", "duration", "date", "bool", "enum", "text"]
    value_raw: str  # must appear in span text (verified)
    span_id: str
    scope: dict[str, str] = {}
    modality: Literal["must", "may", "must_not", "info"] = "info"
    condition_text: str | None = None


class AmendmentDirective(BaseModel):
    action: Literal["substitute", "insert", "delete", "supersede_doc", "supersede_amendment"]
    target_ref: str
    target_path: str | None = None
    effective_date: str | None = None
    new_text_span_ids: list[str] = []
    evidence_span_ids: list[str]


class DraftClaim(BaseModel):
    text: str
    span_ids: list[str]
    kind: Literal["fact", "history", "calc_input"] = "fact"


class Draft(BaseModel):
    claims: list[DraftClaim]
    missing: list[str] = []


class ClaimCheck(BaseModel):
    spans_valid: bool
    numbers_ok: bool
    quote_ok: bool
    version_ok: bool
    hhem: float | None = None
    conflict_ids: list[str] = []


class VerifiedClaim(BaseModel):
    text: str
    span_ids: list[str]
    verdict: Literal["supported", "unsupported", "contradicted"]
    checks: ClaimCheck
    reason: str | None = None


# --- DB rows -----------------------------------------------------------------

class Document(BaseModel):
    doc_id: str
    title: str | None = None
    doc_type: str | None = None
    issuer: str | None = None
    ref_no: str | None = None
    ref_aliases: list[str] = []
    issue_date: str | None = None
    effective_date: str | None = None
    sha256: str | None = None
    filename: str | None = None
    pages: int | None = None
    has_ocr: bool = False
    language: str = "en"
    status: str = "Queued"
    status_detail: str | None = None
    created_at: str | None = None


class Chat(BaseModel):
    chat_id: str
    title: str
    created_at: str
    as_of_date: str | None = None
    language: str = "auto"
    doc_scope: list[str] | None = None


class Message(BaseModel):
    msg_id: str
    chat_id: str
    role: Literal["user", "assistant"]
    content: str
    answer_json: str | None = None
    created_at: str


class RegisterMeta(BaseModel):
    """LLM output of the register step (prompt register_meta)."""

    title: str
    doc_type: Literal["agreement", "schedule", "amendment", "circular", "faq", "policy", "other"] = "other"
    issuer: str | None = None
    ref_no: str | None = None
    ref_aliases: list[str] = []
    issue_date: str | None = None
    effective_date: str | None = None


class Clause(BaseModel):
    clause_id: str
    doc_id: str
    path: str
    heading_trail: str = ""
    kind: str = "other"
    text: str = ""
    page_start: int
    page_end: int
    parent_id: str | None = None
    version_key: str | None = None
    ord: int = 0


class Span(BaseModel):
    span_id: str
    clause_id: str
    doc_id: str
    page: int
    text: str
    bboxes: list[list[float]]
    char_start: int = 0
    char_end: int = 0
    is_table_row: bool = False
    ocr_conf: float | None = None


class Window(BaseModel):
    window_id: str
    clause_id: str
    doc_id: str
    text: str
    span_ids: list[str]
    row_idx: int = -1


class CalcPlan(BaseModel):
    kind: Literal["emi", "late_fee_total", "prepayment_charge", "none"] = "none"
    given: dict[str, float] = {}  # numbers stated in the question: principal, annual_rate_pct, months, ...


class QueryPlan(BaseModel):
    """LLM output of the planner (retrieval.md §1)."""

    intent: Literal["lookup", "multi", "current_rule", "history", "calculation"] = "lookup"
    sub_questions: list[str]
    as_of_override: str | None = None
    calc: CalcPlan = CalcPlan()


class AnswerJSON(BaseModel):
    """What the UI renders and `messages.answer_json` stores (data-model.md §Answer JSON)."""
    status: Literal["answered", "partial", "conflict", "abstained"]
    question: str
    question_en: str | None = None
    language: str = "en"
    as_of_date: str
    intent: str = "lookup"
    claims: list[VerifiedClaim] = []  # supported only
    blocked_claims: list[VerifiedClaim] = []
    disagreements: list[dict] = []
    missing_evidence: list[str] = []
    chains: list[dict] = []
    calculation: dict | None = None
    faithfulness_pct: float | None = None
    drafted: int = 0
    passed: int = 0
    prompt_versions: dict[str, str] = {}
    timings_ms: dict[str, int] = {}
    evidence_spans: list[str] = []  # span ids shown to the drafting model (for audit)


class Extraction(BaseModel):
    """Output of the fact-extraction call (facts-and-subjects.md §2)."""
    facts: list[ExtractedFact] = []


class AmendExtraction(BaseModel):
    """Output of the amendment-directive call (amendments.md §1)."""
    amendments: list[AmendmentDirective] = []


class SameSubject(BaseModel):
    same: bool


class JudgeVerdict(BaseModel):
    conflict: bool
    type: Literal["rule", "eligibility", "text"] = "text"
    explanation: str = ""
