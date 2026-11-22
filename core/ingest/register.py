"""Register step: sha256, doc_id, LLM metadata (verified against the page text), date normalisation (ingest.md §1)."""
from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

import dateparser
import pymupdf

from core import config
from core.llm.client import ModelClient, ModelUnavailable
from core.llm.prompt_loader import load_prompt
from core.models import Document, RegisterMeta

DEMO_NAME = re.compile(r"^(D\d+)_", re.IGNORECASE)
REF_RE = re.compile(r"(?:Reference\s+No\.?|Circular\s+No\.?|Ref\.?\s*No\.?)\s*[:.]?\s*([A-Z0-9][A-Z0-9/\-_.]*[A-Z0-9])")
DATED_RE = re.compile(r"Dated:?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})")
EFFECTIVE_RE = re.compile(r"Effective:?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})")
UPDATED_RE = re.compile(r"Updated:?\s*([A-Za-z]+\s+\d{4})")
TYPE_HINTS = [("amendment", r"\bamendment\b"), ("circular", r"\bcircular\b"), ("schedule", r"schedule of charges"),
              ("faq", r"frequently asked|\bfaq\b"), ("agreement", r"\bagreement\b"), ("policy", r"\bpolicy\b")]


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def make_doc_id(filename: str, sha: str) -> str:
    m = DEMO_NAME.match(filename)
    return m.group(1).upper() if m else "U" + sha[:6]


def first_page_text(path: Path | str) -> str:
    with pymupdf.open(path) as doc:
        return doc[0].get_text()[: config.REGISTER_PAGE_CHARS] if len(doc) else ""


def normalise_date(raw: str | None) -> str | None:
    """'15 January 2024' -> 2024-01-15; month-only dates resolve to the 1st; DMY preference."""
    if not raw:
        return None
    dt = dateparser.parse(raw, settings={"DATE_ORDER": "DMY", "PREFER_DAY_OF_MONTH": "first",
                                         "PREFER_DATES_FROM": "past"})
    return dt.date().isoformat() if dt else None


def ref_variants(ref_no: str | None) -> list[str]:
    if not ref_no:
        return []
    out = [ref_no, ref_no.lower(), re.sub(r"[/\-\s]", "", ref_no).lower()]
    return list(dict.fromkeys(out))


def heuristic_meta(text: str, filename: str = "") -> RegisterMeta:
    """Deterministic metadata used as a fallback and to verify LLM output."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    low = text.lower()
    doc_type = next((t for t, pat in TYPE_HINTS if re.search(pat, low)), "other")
    ref = REF_RE.search(text)
    dated, eff, upd = DATED_RE.search(text), EFFECTIVE_RE.search(text), UPDATED_RE.search(text)
    return RegisterMeta(
        title=lines[0].title() if lines and lines[0].isupper() else (lines[0] if lines else Path(filename).stem),
        doc_type=doc_type,  # type: ignore[arg-type]
        issuer=None, ref_no=ref.group(1) if ref else None,
        issue_date=dated.group(1) if dated else (upd.group(1) if upd else None),
        effective_date=eff.group(1) if eff else (upd.group(1) if upd else None))


def extract_meta(text: str, filename: str, client: ModelClient | None = None) -> tuple[RegisterMeta, str]:
    """LLM metadata; any value not literally supported by the page text is replaced by the heuristic one.

    Returns (meta, source) with source in {"llm", "heuristic"}.
    """
    fallback = heuristic_meta(text, filename)
    if not text.strip():
        return fallback, "heuristic"
    _, prompt = load_prompt("register_meta")
    try:
        meta = (client or _client()).chat_json(
            [{"role": "system", "content": prompt}, {"role": "user", "content": text}], RegisterMeta, max_tokens=300)
    except ModelUnavailable:
        return fallback, "heuristic"
    flat = re.sub(r"\s+", "", text).lower()
    if not meta.ref_no or re.sub(r"\s+", "", meta.ref_no).lower() not in flat:
        meta.ref_no = fallback.ref_no
    for fld in ("issue_date", "effective_date"):
        val = getattr(meta, fld)
        if val and normalise_date(val) is None:
            setattr(meta, fld, getattr(fallback, fld))
    if not meta.title.strip():
        meta.title = fallback.title
    return meta, "llm"


def _client() -> ModelClient:
    from core.llm.client import get_client
    return get_client()


def build_document(doc_id: str, path: Path, sha: str, meta: RegisterMeta | None, today: date | None = None) -> Document:
    """Assemble the documents row; effective_date falls back to issue_date, then today (flagged)."""
    detail = None
    if meta is None:
        return Document(doc_id=doc_id, title=path.stem, sha256=sha, filename=path.name, status="Queued")
    issue, eff = normalise_date(meta.issue_date), normalise_date(meta.effective_date)
    eff = eff or issue
    if eff is None:
        eff = (today or date.today()).isoformat()
        detail = "no date found; effective date defaulted to today"
    aliases = list(dict.fromkeys([*meta.ref_aliases, *ref_variants(meta.ref_no)]))
    return Document(doc_id=doc_id, title=meta.title, doc_type=meta.doc_type, issuer=meta.issuer, ref_no=meta.ref_no,
                    ref_aliases=aliases, issue_date=issue, effective_date=eff, sha256=sha, filename=path.name,
                    status="Parsing", status_detail=detail)
